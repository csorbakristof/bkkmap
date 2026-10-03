"""Connection Scan Algorithm (earliest arrival) routing engine."""
import logging

import numpy as np
from scipy.spatial import cKDTree

from config import MAX_TRANSFER_WALK_MIN
from geo import haversine_m, local_xy_m, max_walk_radius_m, walk_minutes

log = logging.getLogger(__name__)


def build_footpaths(stops_df, walk_speed, max_transfer_walk=MAX_TRANSFER_WALK_MIN):
    """Walking transfers between nearby stops: list (per stop) of (neighbor, seconds)."""
    lat, lon = stops_df["lat"].to_numpy(), stops_df["lon"].to_numpy()
    xy = local_xy_m(lat, lon, float(np.mean(lat)))
    pairs = cKDTree(xy).query_pairs(max_walk_radius_m(max_transfer_walk, walk_speed), output_type="ndarray")
    footpaths = [[] for _ in range(len(stops_df))]
    if len(pairs):
        a, b = pairs[:, 0], pairs[:, 1]
        secs = np.ceil(walk_minutes(haversine_m(lat[a], lon[a], lat[b], lon[b]), walk_speed) * 60).astype(int)
        for i, j, s in zip(a.tolist(), b.tolist(), secs.tolist()):
            footpaths[i].append((j, s))
            footpaths[j].append((i, s))
    log.info("Footpaths: %d stop pairs within %.0f min walk", len(pairs), max_transfer_walk)
    return footpaths


def solve_csa(connections_df, stops_df, start_lat, start_lon, departure_sec, walk_speed,
              max_walk_time, transfer_penalty, max_cutoff, footpaths=None):
    """Earliest arrival time (seconds after midnight) at every stop; np.inf if unreached.

    Staying on the same trip is free; boarding a different vehicle after having
    ridden one costs `transfer_penalty` minutes. The first boarding after the
    initial walk from the origin is not penalized.
    """
    n = len(stops_df)
    if footpaths is None:
        footpaths = build_footpaths(stops_df, walk_speed)

    inf = float("inf")
    tau = [inf] * n      # earliest arrival at stop
    ready = [inf] * n    # earliest time a new vehicle can be boarded at stop
    penalty = int(round(transfer_penalty * 60))

    walk = walk_minutes(haversine_m(start_lat, start_lon, stops_df["lat"].to_numpy(), stops_df["lon"].to_numpy()),
                        walk_speed)
    for s in np.flatnonzero(walk <= max_walk_time).tolist():
        tau[s] = ready[s] = departure_sec + walk[s] * 60.0
    log.info("CSA: %d stops reachable on foot from origin", int((walk <= max_walk_time).sum()))

    t_end = departure_sec + max_cutoff * 60
    t_dep_all = connections_df["t_dep"].to_numpy()
    lo, hi = np.searchsorted(t_dep_all, [departure_sec, t_end], side="left")
    window = connections_df.iloc[lo:hi]
    log.info("CSA: scanning %d connections departing in the %.0f min window", len(window), max_cutoff)

    trip_on = bytearray(int(connections_df["trip_id"].max()) + 1 if len(connections_df) else 0)
    for dep, arr, td, ta, trip in zip(window["s_dep"].tolist(), window["s_arr"].tolist(),
                                      window["t_dep"].tolist(), window["t_arr"].tolist(),
                                      window["trip_id"].tolist()):
        if trip_on[trip] or ready[dep] <= td:
            trip_on[trip] = 1
            if ta < tau[arr]:
                tau[arr] = ta
                if ta + penalty < ready[arr]:
                    ready[arr] = ta + penalty
                for nb, w in footpaths[arr]:
                    t = ta + w
                    if t < tau[nb]:
                        tau[nb] = t
                    if t + penalty < ready[nb]:
                        ready[nb] = t + penalty

    tau = np.array(tau, dtype=float)
    log.info("CSA: %d of %d stops reached", int(np.isfinite(tau).sum()), n)
    return tau

"""Car travel times: Dijkstra over the OSM road graph, then snapping grid cells to road nodes."""
import logging

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from config import CAR_ORIGIN_SNAP_M, CAR_PARK_SNAP_M, CAR_SNAP_NEIGHBORS
from geo import haversine_m, local_xy_m, walk_minutes
from osm_roads import access_nodes, edge_minutes

log = logging.getLogger(__name__)

CELL_CHUNK = 200_000


def solve_car(g, start_lat, start_lon, walk_speed, access_min, traffic_factor, max_cutoff):
    """Minutes from the origin to every road node (inf if beyond max_cutoff).

    The drive may start at any non-motorway node within CAR_ORIGIN_SNAP_M of the origin,
    after walking there and spending access_min getting into the car.
    """
    n = len(g.node_lat)
    starts = np.flatnonzero(access_nodes(g))
    if not len(starts):
        raise RuntimeError("No car-accessible roads inside the bounding box")
    d = haversine_m(start_lat, start_lon, g.node_lat[starts], g.node_lon[starts])
    near = d <= CAR_ORIGIN_SNAP_M
    if not near.any():
        near = d == d.min()
        log.warning("Car: nearest road is %.0f m from the origin", d.min())
    seeds, seed_min = starts[near], walk_minutes(d[near], walk_speed) + access_min
    log.info("Car: %d road nodes within reach of the origin", len(seeds))

    # Virtual source node n (+epsilon, explicit zeros are dropped from sparse matrices).
    src = np.concatenate([g.edge_src, np.full(len(seeds), n)]).astype(np.int64)
    dst = np.concatenate([g.edge_dst, seeds]).astype(np.int64)
    wt = np.concatenate([edge_minutes(g, traffic_factor), seed_min + 1e-6])
    # csr_matrix sums duplicate entries; parallel edges (e.g. two ways between the same nodes) keep the fastest.
    order = np.lexsort((wt, dst, src))
    _, first = np.unique(src[order] * (n + 1) + dst[order], return_index=True)
    keep = order[first]
    src, dst, wt = src[keep], dst[keep], wt[keep]
    graph = csr_matrix((wt, (src, dst)), shape=(n + 1, n + 1))
    t = dijkstra(graph, directed=True, indices=n, limit=max_cutoff)[:n]
    log.info("Car: %d of %d road nodes reached", np.isfinite(t).sum(), n)
    return t


def car_cell_minutes(g, node_minutes, cell_lat, cell_lon, walk_speed, egress_min, max_cutoff):
    """Door-to-door car time per cell: drive to a nearby parkable node, park, walk to the cell.

    Cells farther than CAR_PARK_SNAP_M from any reached road get inf here and are later
    covered by grid walking propagation.
    """
    out = np.full(len(cell_lat), np.inf)
    ok = np.flatnonzero(access_nodes(g) & (node_minutes + egress_min < max_cutoff))
    if not len(ok):
        return out
    p_lat, p_lon, p_min = g.node_lat[ok], g.node_lon[ok], node_minutes[ok] + egress_min
    lat0 = float(np.mean(cell_lat))
    tree = cKDTree(local_xy_m(p_lat, p_lon, lat0))
    k = min(CAR_SNAP_NEIGHBORS, len(ok))
    for start in range(0, len(cell_lat), CELL_CHUNK):
        sl = slice(start, start + CELL_CHUNK)
        dist, idx = tree.query(local_xy_m(cell_lat[sl], cell_lon[sl], lat0), k=k,
                               distance_upper_bound=CAR_PARK_SNAP_M)
        dist, idx = dist.reshape(len(dist), k), idx.reshape(len(idx), k)
        found = np.isfinite(dist)
        tot = np.full(dist.shape, np.inf)
        tot[found] = p_min[idx[found]] + walk_minutes(dist[found], walk_speed)
        out[sl] = tot.min(axis=1)
    return out

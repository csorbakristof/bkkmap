"""Spatial travel-time grid evaluation."""
import logging
import math

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree

from config import EPSG_WEB_MERCATOR, EPSG_WGS84
from geo import haversine_m, local_xy_m, max_walk_radius_m, walk_minutes

log = logging.getLogger(__name__)

CELL_CHUNK = 50_000

_to_merc = Transformer.from_crs(EPSG_WGS84, EPSG_WEB_MERCATOR, always_xy=True)
_to_wgs = Transformer.from_crs(EPSG_WEB_MERCATOR, EPSG_WGS84, always_xy=True)


def make_grid(bbox, resolution_m):
    """Regular grid in Web Mercator whose cells are ~resolution_m on the ground.

    Row 0 is the northern edge so the matrix can be shown with imshow(origin='upper').
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    x0, y0 = _to_merc.transform(min_lon, min_lat)
    x1, y1 = _to_merc.transform(max_lon, max_lat)
    # Mercator stretches distances by 1/cos(lat).
    step = resolution_m / math.cos(math.radians((min_lat + max_lat) / 2))
    ncols = max(1, int(math.ceil((x1 - x0) / step)))
    nrows = max(1, int(math.ceil((y1 - y0) / step)))
    xs = x0 + (np.arange(ncols) + 0.5) * step
    ys = y0 + nrows * step - (np.arange(nrows) + 0.5) * step
    gx, gy = np.meshgrid(xs, ys)
    lon, lat = _to_wgs.transform(gx, gy)
    extent = (x0, x0 + ncols * step, y0, y0 + nrows * step)  # left, right, bottom, top
    return lat, lon, extent


def compute_travel_time_grid(bbox, resolution_m, start_lat, start_lon, stops_df, tau, departure_sec,
                             walk_speed, max_walk_time, max_cutoff):
    """Travel time in minutes for every grid cell, capped at max_cutoff.

    Returns (grid_minutes [nrows, ncols], extent_3857).
    """
    lat, lon, extent = make_grid(bbox, resolution_m)
    log.info("Grid: %d x %d cells at %.0f m", lat.shape[1], lat.shape[0], resolution_m)
    flat_lat, flat_lon = lat.ravel(), lon.ravel()

    best = walk_minutes(haversine_m(start_lat, start_lon, flat_lat, flat_lon), walk_speed)

    rel = (tau - departure_sec) / 60.0
    reached = np.flatnonzero(np.isfinite(rel) & (rel <= max_cutoff))
    if len(reached):
        s_lat = stops_df["lat"].to_numpy()[reached]
        s_lon = stops_df["lon"].to_numpy()[reached]
        s_rel = rel[reached]
        lat0 = float(np.mean(flat_lat))
        stop_tree = cKDTree(local_xy_m(s_lat, s_lon, lat0))
        # Small margin so the approximate planar search never misses a valid pair.
        radius = max_walk_radius_m(max_walk_time, walk_speed) * 1.01
        cell_xy = local_xy_m(flat_lat, flat_lon, lat0)
        for start in range(0, len(flat_lat), CELL_CHUNK):
            sl = slice(start, start + CELL_CHUNK)
            pairs = cKDTree(cell_xy[sl]).sparse_distance_matrix(stop_tree, radius, output_type="ndarray")
            if not len(pairs):
                continue
            ci, si = pairs["i"], pairs["j"]
            w = walk_minutes(haversine_m(flat_lat[sl][ci], flat_lon[sl][ci], s_lat[si], s_lon[si]), walk_speed)
            ok = w <= max_walk_time
            np.minimum.at(best, ci[ok] + start, s_rel[si[ok]] + w[ok])

    grid = np.minimum(best, max_cutoff).reshape(lat.shape)
    log.info("Grid: travel times %.1f - %.1f min", grid.min(), grid.max())
    return grid, extent

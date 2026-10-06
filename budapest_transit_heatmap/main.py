"""CLI entry point: GTFS download -> timetable -> CSA routing -> grid -> PNG map."""
import argparse
import logging
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from config import DEFAULT_BBOX, OVERLAY_ALPHA
from csa_solver import solve_csa
from downloader import download_gtfs_feeds
from grid_evaluator import compute_travel_time_grid
from gtfs_parser import build_timetable
from renderer import render_map

log = logging.getLogger("transit_heatmap")


def next_monday_9am(now=None):
    """09:00 on the first Monday strictly after today."""
    now = now or datetime.now()
    days = 7 - now.weekday()  # Monday is 0; if today is Monday this gives 7
    return (now + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Public transit travel-time heatmap for Budapest & Érd.")
    p.add_argument("--start-lat", type=float, required=True, help="Origin latitude, e.g. 47.4979")
    p.add_argument("--start-lon", type=float, required=True, help="Origin longitude, e.g. 19.0402")
    p.add_argument("--datetime", type=datetime.fromisoformat, default=None,
                   help="Departure time, YYYY-MM-DDTHH:MM:SS (default: next Monday 09:00)")
    p.add_argument("--bbox", type=float, nargs=4, default=list(DEFAULT_BBOX),
                   metavar=("MIN_LAT", "MIN_LON", "MAX_LAT", "MAX_LON"))
    p.add_argument("--resolution", type=int, default=67, help="Grid cell size in meters")
    p.add_argument("--walk-speed", type=float, default=4.0, help="Walking speed in km/h")
    p.add_argument("--max-walk-time", type=float, default=30.0, help="Max walk to/from stops in minutes")
    p.add_argument("--transfer-penalty", type=float, default=3.0, help="Minutes added per vehicle change")
    p.add_argument("--max-cutoff", type=float, default=180.0, help="Travel time horizon in minutes")
    p.add_argument("--output", default="transit_heatmap.png")
    p.add_argument("--width-px", type=int, default=6000, help="Width of the map area in the output image (pixels)")
    p.add_argument("--overlay-alpha", type=float, default=OVERLAY_ALPHA, help="Opacity of the heatmap layer (0-1)")
    p.add_argument("--contour-interval", type=float, default=15.0, help="Isochrone contour spacing in minutes")
    p.add_argument("--cache-dir", default="./gtfs_cache")
    p.add_argument("--extra-feed", action="append", default=[],
                   help="Additional GTFS zip (URL or local path); may be repeated")
    args = p.parse_args(argv)

    min_lat, min_lon, max_lat, max_lon = args.bbox
    if not (min_lat < max_lat and min_lon < max_lon):
        p.error("--bbox must be MIN_LAT MIN_LON MAX_LAT MAX_LON")
    if args.resolution <= 0 or args.walk_speed <= 0 or args.max_cutoff <= 0 or args.width_px <= 0:
        p.error("--resolution, --walk-speed, --max-cutoff and --width-px must be positive")
    if args.datetime is None:
        args.datetime = next_monday_9am()
    return args


@contextmanager
def step(name):
    log.info("== %s", name)
    t0 = time.perf_counter()
    yield
    log.info("== %s done in %.1f s", name, time.perf_counter() - t0)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    args = parse_args(argv)
    dt = args.datetime
    departure_sec = dt.hour * 3600 + dt.minute * 60 + dt.second
    cache_dir = Path(args.cache_dir)

    with step("Download GTFS feeds"):
        feeds = download_gtfs_feeds(cache_dir, extra_feeds=args.extra_feed)
    with step("Build timetable"):
        stops, connections = build_timetable(feeds, dt.date(), args.bbox, cache_dir)
    with step("Route (Connection Scan)"):
        tau = solve_csa(connections, stops, args.start_lat, args.start_lon, departure_sec, args.walk_speed,
                        args.max_walk_time, args.transfer_penalty, args.max_cutoff)
    with step("Evaluate grid"):
        grid, extent = compute_travel_time_grid(args.bbox, args.resolution, args.start_lat, args.start_lon, stops,
                                                tau, departure_sec, args.walk_speed, args.max_walk_time,
                                                args.max_cutoff)
    with step("Render map"):
        metadata = [
            f"Departure: {dt:%Y-%m-%d %H:%M} ({dt:%A})",
            f"Origin: {args.start_lat:.5f}, {args.start_lon:.5f}",
            f"Travel time: {grid.min():.0f}-{grid.max():.0f} min (cap {args.max_cutoff:.0f})",
            f"Walk {args.walk_speed:g} km/h, max {args.max_walk_time:g} min; transfer +{args.transfer_penalty:g} min",
            f"Feeds: {', '.join(feeds)}  |  grid {args.resolution} m",
        ]
        render_map(grid, extent, args.bbox, args.start_lat, args.start_lon, args.output, metadata,
                   tile_cache=cache_dir / "tiles", width_px=args.width_px,
                   overlay_alpha=args.overlay_alpha, contour_interval=args.contour_interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())

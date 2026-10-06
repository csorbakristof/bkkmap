"""CLI entry point: GTFS / OSM roads -> transit (CSA) and car (Dijkstra) routing -> grid -> PNG map."""
import argparse
import logging
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from car_router import car_cell_minutes, solve_car
from config import (CONTOUR_INTERVAL_MIN, DEFAULT_BBOX, DEFAULT_CAR_ACCESS_MIN, DEFAULT_CAR_EGRESS_MIN,
                    OVERLAY_ALPHA)
from csa_solver import solve_csa
from downloader import download_gtfs_feeds, download_osm_pbf
from grid_evaluator import compute_travel_time_grid
from gtfs_parser import build_timetable
from osm_roads import load_road_graph
from renderer import render_map

log = logging.getLogger("transit_heatmap")


def next_monday_9am(now=None):
    """09:00 on the first Monday strictly after today."""
    now = now or datetime.now()
    days = 7 - now.weekday()  # Monday is 0; if today is Monday this gives 7
    return (now + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Public transit / car travel-time heatmap for Budapest & Érd.")
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
    p.add_argument("--contour-interval", type=float, default=CONTOUR_INTERVAL_MIN, help="Isochrone contour spacing in minutes")
    p.add_argument("--cache-dir", default="./gtfs_cache")
    p.add_argument("--extra-feed", action="append", default=[],
                   help="Additional GTFS zip (URL or local path); may be repeated")
    p.add_argument("--transit", action=argparse.BooleanOptionalAction, default=True,
                   help="Include public transport (default: on)")
    p.add_argument("--car", action=argparse.BooleanOptionalAction, default=False,
                   help="Include driving on OpenStreetMap roads (default: off)")
    p.add_argument("--osm-pbf", default=None,
                   help="OSM extract for car routing (local .osm.pbf or URL; default: Geofabrik Hungary)")
    p.add_argument("--traffic-factor", type=float, default=1.0,
                   help="Multiplier on modelled car speeds (<1 = heavier traffic)")
    p.add_argument("--car-access-min", type=float, default=DEFAULT_CAR_ACCESS_MIN,
                   help="Minutes to get into the car and start driving")
    p.add_argument("--car-egress-min", type=float, default=DEFAULT_CAR_EGRESS_MIN,
                   help="Minutes to find parking and leave the car")
    args = p.parse_args(argv)

    min_lat, min_lon, max_lat, max_lon = args.bbox
    if not (min_lat < max_lat and min_lon < max_lon):
        p.error("--bbox must be MIN_LAT MIN_LON MAX_LAT MAX_LON")
    if args.resolution <= 0 or args.walk_speed <= 0 or args.max_cutoff <= 0 or args.width_px <= 0:
        p.error("--resolution, --walk-speed, --max-cutoff and --width-px must be positive")
    if not (args.transit or args.car):
        p.error("enable at least one mode: --transit and/or --car")
    if args.traffic_factor <= 0 or args.car_access_min < 0 or args.car_egress_min < 0:
        p.error("--traffic-factor must be positive, --car-access-min/--car-egress-min non-negative")
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

    stops = tau = feeds = None
    if args.transit:
        with step("Download GTFS feeds"):
            feeds = download_gtfs_feeds(cache_dir, extra_feeds=args.extra_feed)
        with step("Build timetable"):
            stops, connections = build_timetable(feeds, dt.date(), args.bbox, cache_dir)
        with step("Route (Connection Scan)"):
            tau = solve_csa(connections, stops, args.start_lat, args.start_lon, departure_sec, args.walk_speed,
                            args.max_walk_time, args.transfer_penalty, args.max_cutoff)

    car_minutes = None
    if args.car:
        with step("Load road network"):
            roads = load_road_graph(download_osm_pbf(cache_dir, args.osm_pbf), args.bbox, cache_dir)
        with step("Route (car Dijkstra)"):
            node_minutes = solve_car(roads, args.start_lat, args.start_lon, args.walk_speed, args.car_access_min,
                                     args.traffic_factor, args.max_cutoff)

        def car_minutes(cell_lat, cell_lon):
            return car_cell_minutes(roads, node_minutes, cell_lat, cell_lon, args.walk_speed, args.car_egress_min,
                                    args.max_cutoff)

    with step("Evaluate grid"):
        grid, extent = compute_travel_time_grid(args.bbox, args.resolution, args.start_lat, args.start_lon, stops,
                                                tau, departure_sec, args.walk_speed, args.max_walk_time,
                                                args.max_cutoff, car_minutes=car_minutes)
    with step("Render map"):
        modes = " + ".join(m for m, on in (("public transport", args.transit), ("car", args.car)) if on)
        metadata = [
            f"Departure: {dt:%Y-%m-%d %H:%M} ({dt:%A})",
            f"Origin: {args.start_lat:.5f}, {args.start_lon:.5f}",
            f"Modes: {modes} (fastest per cell)",
            f"Travel time: {grid.min():.0f}-{grid.max():.0f} min (cap {args.max_cutoff:.0f})",
            f"Walk {args.walk_speed:g} km/h, max {args.max_walk_time:g} min"
            + (f"; transfer +{args.transfer_penalty:g} min" if args.transit else ""),
        ]
        if args.car:
            metadata.append(f"Car: OSM roads, traffic factor {args.traffic_factor:g}, "
                            f"+{args.car_access_min:g} min start, +{args.car_egress_min:g} min parking")
        metadata.append((f"Feeds: {', '.join(feeds)}  |  " if args.transit else "") + f"grid {args.resolution} m")
        render_map(grid, extent, args.bbox, args.start_lat, args.start_lon, args.output, metadata,
                   tile_cache=cache_dir / "tiles", width_px=args.width_px,
                   overlay_alpha=args.overlay_alpha, contour_interval=args.contour_interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())

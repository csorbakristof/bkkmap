# Plan: optional car travel (OSM road network) in bkkmap

**Status:** implemented (see README "Car travel"). Notes below are updated where the implementation deviated.

## Context
Today the app only models public transit: GTFS → Connection Scan (`csa_solver.py`) → per-stop arrival times → `compute_travel_time_grid` (`grid_evaluator.py`) → PNG (`renderer.py`). We want an optional **car** mode whose travel times come from OpenStreetMap roads, plus switches to turn **car** and **mass transportation** on or off independently. With both on, each cell shows the faster of the two (door-to-door fastest mode).

## How to estimate car travel times from OpenStreetMap
OSM has geometry and tags but no live traffic, so times are *free-flow-based estimates*:

1. **Road graph** from OSM `highway=*` ways that allow cars (motorway…residential, `*_link`, `living_street`, `unclassified`; exclude footway, cycleway, path, pedestrian, steps, `access=no/private`, `motor_vehicle=no`; include `ferry` routes optionally). Respect `oneway` (`yes/-1/reversible`, motorways implicitly one-way, `junction=roundabout`). Turn restrictions are ignored in v1 (documented simplification).
2. **Edge length**: haversine along the way's node sequence (reuse `haversine_m` in `geo.py`).
3. **Edge speed**: `maxspeed` tag if present (parse `50`, `50 mph`, `HU:urban`=50, `HU:rural`=90, `HU:motorway`=130, `walk`/`none`); otherwise Hungarian defaults per `highway` class: motorway 130, trunk 110, primary 90, secondary 80, tertiary 70, unclassified 50, residential 30–50, living_street 20; inside built-up areas (`maxspeed` missing, residential/tertiary) 50.
4. **Realism factors** (all in `config.py`, tunable):
   - effective speed = speed × class factor (motorway 0.9, urban roads 0.6–0.7 to account for congestion/signals at the Monday 09:00 default; a `--traffic-factor` multiplier);
   - fixed penalties: `highway=traffic_signals` node +15 s average, stop/give-way +5 s, junction turn penalty small constant;
   - **access/egress overhead**: walk from origin to the car (`--car-access-min`, default 2 min) and parking + walk to destination (`--car-egress-min`, default 5 min, higher in dense areas optional).
5. **Routing**: build a `scipy.sparse` directed graph (nodes = OSM nodes, weights = seconds) and run `scipy.sparse.csgraph.dijkstra(indices=origin_node, limit=max_cutoff*60)` — the same pattern already used in `propagate_walking`. No new routing engine needed. Origin snapped to the nearest road node with a `cKDTree` (walk to it counted).
6. **Mapping to the grid**: each grid cell snaps to its nearest *reached* road node (`cKDTree`, reuse `local_xy_m` in `geo.py`); cell time = node drive time + off-road walk (haversine × `WALK_DETOUR_FACTOR`, `walk_minutes`) + egress overhead; cells farther than `--max-walk-time` from a road stay unreached by car and fall back to transit/walk. Finally run the existing `propagate_walking` so cells fade out smoothly.
7. **Combining modes**: `grid = min(transit_grid, car_grid)`; transit-only and car-only are special cases. (Mixed park-and-ride is out of scope.)

**Data source** (recommended): Geofabrik `hungary-latest.osm.pbf` (~300 MB, one download, updated daily), parsed with a small built-in numpy PBF reader (`osm_pbf.py`; pyosmium was planned but its DLL is blocked by the Windows application control policy on the dev machine), cached once as `gtfs_cache/parsed/roads_<extract>_<mtime>_v1.npz` and cut to bbox + buffer on every run (node coords, edge src/dst/seconds) — same caching idea as the parsed-GTFS `.npz` in `gtfs_parser.py`. Alternatives rejected: Overpass API (rate-limited, fails for a country-wide bbox; acceptable only as a future fallback for small bboxes), OSMnx/routing servers (heavy dependencies, not pure-Python-light). Respect OSM data licence: keep the existing "© OpenStreetMap contributors" attribution.

## Implementation steps
1. `config.py`: add `ROAD_PBF_URL`, per-class default speeds, speed/traffic factors, signal/stop penalties, default access/egress minutes, `CAR_BBOX_BUFFER_M`.
2. New `osm_roads.py`:
   - `download_pbf(cache_dir)` (reuse the HTTP/user-agent/age-check pattern in `downloader.py`; also accept `--osm-pbf PATH`).
   - `load_road_graph(pbf, bbox, cache_dir)` → arrays (node_lat, node_lon, edge_src, edge_dst, edge_sec); parse `maxspeed`, `oneway`, signals; cache to `.npz`.
3. New `car_router.py`: `solve_car(graph, start_lat, start_lon, max_cutoff, params)` → per-node minutes (Dijkstra), and `car_grid(...)` that snaps cells to nodes and returns a grid in the same shape/extent as `make_grid` (reuse `make_grid`, `propagate_walking`, `cKDTree` usage from `grid_evaluator.py`).
4. `grid_evaluator.py`: refactor `compute_travel_time_grid` so the transit part is optional (`tau is None` → skip) and accept an optional car seed array that is min-merged into `best` **before** `propagate_walking`; keeps transit-only output identical.
5. `main.py` configuration options:
   - Boolean flags `--car/--no-car` and `--transit/--no-transit` (`argparse.BooleanOptionalAction`, defaults: car off, transit on — backward compatible). Error if both are off.
   - `--osm-pbf`, `--traffic-factor`, `--car-access-min`, `--car-egress-min`.
   - Skip GTFS download/timetable/CSA entirely when transit is off; skip PBF work when car is off.
   - Add mode and car parameters to the on-map `metadata` lines and log lines.
6. No new dependency (see data source). README: document modes, data download, assumptions.

## Critical files
`budapest_transit_heatmap/main.py`, `grid_evaluator.py`, `config.py`, `downloader.py`, `geo.py` (reused helpers), new `osm_pbf.py`, `osm_roads.py`, `car_router.py`, `README.md`.

## Performance notes
Hungary graph ≈ 3–5 M nodes / 8–10 M directed edges: PBF parse once (minutes), cached afterwards; Dijkstra with `limit` on scipy is seconds to tens of seconds; memory a few GB at most. The 100 m country grid (16 M cells) is the heaviest part, already handled by chunked KD-tree queries.

## Known limitations (to document)
No live/historical traffic, no turn restrictions or turn costs beyond a constant, no tolls/closures, simplified urban congestion factor, no parking search model beyond a constant, no park-and-ride.

## Verification
1. Unit-style checks: `maxspeed` parser cases; one-way handling on a tiny hand-made graph; Dijkstra result on a 4-node graph.
2. Run `--modes transit` and compare with an existing output (e.g. `out/baloo.png` parameters) — must be unchanged.
3. Run `--modes car` for Budapest (Hunor utca 19, 2026-10-12 09:00, `--resolution 200 --width-px 2000`): sanity-check known trips (e.g. Óbuda→Budapest Airport ≈ 35–45 min, →Győr ≈ 60–70 min by motorway) and that motorways visibly extend contours.
4. Run `--modes transit,car` and verify `combined ≤ min(each)` cellwise (log assert) and that both-off exits with a clear error.
5. Whole-country run at 1000 m for timing/memory.

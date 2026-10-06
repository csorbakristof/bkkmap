# bkkmap
Generate heat maps according to mass transportation transit times.

Implements [the specification](gemini_spec-budapest_rd_transit_isochrone_map_generator_specification.md):
pure-Python GTFS download → Connection Scan routing → travel-time grid → PNG map on an OSM basemap.

## Setup
```
python -m venv .venv
.venv\Scripts\activate        # Windows  (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
```

## Usage
```
python budapest_transit_heatmap/main.py --start-lat 47.4979 --start-lon 19.0402 --datetime 2026-10-05T08:00:00
```
See `--help` for all options (bbox, resolution, walk speed, transfer penalty, cutoff, output, cache dir).
Defaults: departure next Monday 09:00, 67 m grid, 6000 px wide map (a ~6700 px, ~35 MB image; the first run
downloads ~600 OSM tiles, cached afterwards). For a quick preview use e.g. `--resolution 200 --width-px 2000`.

The first run downloads the BKK feed (~56 MB) and parses that day's timetable (~10 s); both are cached in
`--cache-dir`, so later runs for the same date only take the time needed to fetch basemap tiles.

## Regional feeds (MÁV / Volánbusz)
The BKK feed does not cover Érd or the regional trains. MÁV-csoport only gives out its GTFS after
[registration](https://www.mavcsoport.hu/gtfs-igenybejelento); the mirror URLs in the spec are offline.
Once you have the archives, drop them into the cache dir as `mav.zip` / `volan.zip` (picked up automatically), or pass
`--extra-feed path/or/url.zip` (repeatable). All feeds are merged into one timetable.

## Modelling notes
- Walking = haversine distance × 1.25 at the given speed; transfers between stops within a 5 min walk are allowed.
- `--max-walk-time` limits the walk from the origin to the first stop. The walk after the last stop is unlimited
  (propagated over the grid), so travel times fade out smoothly beyond the transit network.
- The transfer penalty applies whenever you board a new vehicle after having ridden one.
- Trips from the previous service day running past midnight are included.
- Cells beyond `--max-cutoff` are capped at the top color.

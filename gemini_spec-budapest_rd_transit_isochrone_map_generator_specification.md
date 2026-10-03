# Technical Specification: Budapest & Érd Mass Transit Travel-Time Heatmap Generator

## 1. Overview & Objective
This application generates a high-resolution raster heatmap (`.png`) displaying estimated public transit travel durations from a specified starting location and departure time to every point across Budapest and the Érd agglomeration area.

The system features:
- **Pure Python Execution:** Zero external native binary dependencies (no Java runtime, C-compilation tools, GDAL/Fiona, Docker, or external routing engines). Runs seamlessly in any standard Python environment (e.g., GitHub Copilot Agent mode in VS Code).
- **Automated Data Pipeline:** Automatic fetching, caching, and merging of public static GTFS schedules for Budapest (BKK) and regional rail/bus services (MÁV / Volánbusz).
- **Multimodal Time-Dependent Routing:** Incorporates timetable schedules, exact departure times, transfer time penalties, first/last-mile walking, and direct walking fallback.
- **Cartographic Map Export:** High-density pixel heatmap overlaid on OpenStreetMap raster background with dynamic color scale normalized to the bounding box's calculated travel times, legend, scale bar, and start-point indicators.

---

## 2. Confirmed Technical Decisions & Requirements

1. **Walking Route Calculation:**
   - **Method:** Geodesic (Haversine) distance multiplied by a detour coefficient ($1.25$) to model real street geometry without requiring heavy OSM street graph parsing or C-based spatial libraries.
   - **Walk Speed:** $4.0 \text{ km/h}$ ($\approx 66.67 \text{ meters/minute}$).
   - **Max Walking Horizon:** $30 \text{ minutes}$ to/from transit stops. If no transit option reaches a point, direct walking travel time is evaluated for every pixel across the entire map extent.

2. **GTFS Feeds & Data Sources:**
   - Fully automated URL-based downloading.
   - **BKK GTFS URL:** `https://go.bkk.hu/api/static/v1/public-gtfs/budapest_gtfs.zip`
   - **MÁV / Regional GTFS URL:** Automated fallback download from standard Hungarian public transit GTFS mirrors (e.g., `https://gtfs.menetbrand.com/mav/gtfs.zip` and `https://gtfs.menetbrand.com/volanbusz/gtfs.zip`).
   - Cached locally in `--cache-dir` with automatic weekly re-downloads.

3. **Color Palette Normalization:**
   - Palette limits are dynamically calibrated to the **actual minimum and maximum calculated travel times** within the chosen bounding box grid.
   - Pixels exceeding `--max-cutoff` (default $180$ mins) or unreached points are capped at the maximum color interval.

4. **Dependencies & Dev Environment Strategy:**
   - **Strict Dependency Rule:** Must rely exclusively on standard PyPI packages provided with binary wheels (`pip install numpy pandas scipy matplotlib requests pillow pyproj`).
   - No `OSMnx`, `geopandas`, `fiona`, `gdal`, or Java/OTP dependencies.
   - Map tiles fetched directly via `requests` and transformed into Mercator projection using lightweight `pyproj` + `PIL`.

---

## 3. Command Line Interface (CLI) Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--start-lat` | `float` | **Required** | Latitude of origin (e.g., `47.3783` for Érd or `47.4979` for Budapest). |
| `--start-lon` | `float` | **Required** | Longitude of origin (e.g., `18.9181`). |
| `--datetime` | `string` | *Current Time* | Departure date & time in ISO format (`YYYY-MM-DDTHH:MM:SS`). |
| `--bbox` | `float x 4` | `47.25 18.80 47.60 19.30` | Map Bounding box: `min_lat min_lon max_lat max_lon`. |
| `--resolution` | `int` | `200` | Spatial resolution of raster grid cells in meters (e.g., 200m). |
| `--walk-speed` | `float` | `4.0` | Assumed walking speed in km/h. |
| `--max-walk-time` | `float` | `30.0` | Maximum allowed walk time to/from transit stops (minutes). |
| `--transfer-penalty`| `float` | `3.0` | Transfer penalty added per transit line change (minutes). |
| `--max-cutoff` | `float` | `180.0` | Horizon limit in minutes (3 hours). |
| `--output` | `string` | `transit_heatmap.png` | Path for the generated map image. |
| `--cache-dir` | `string` | `./gtfs_cache` | Directory to store GTFS feed downloads. |

---

## 4. Mathematical & Algorithmic Formulation

### 4.1 Geodesic Detour Walking Formula
Given latitude/longitude points $A(\phi_1, \lambda_1)$ and $B(\phi_2, \lambda_2)$:
$$d_{haversine}(A, B) = 2 R \arcsin \left( \sqrt{\sin^2\left(\frac{\Delta\phi}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\Delta\lambda}{2}\right)} \right)$$
where $R = 6,371,000 \text{ meters}$.

The walking duration in minutes is:
$$T_{walk}(A, B) = \frac{d_{haversine}(A, B) \times 1.25}{v_{walk\_m\_per\_min}} \quad \text{where } v_{walk\_m\_per\_min} = \frac{4.0 \times 1000}{60} \approx 66.67 \text{ m/min}$$

### 4.2 Connection Scan Algorithm (CSA)
CSA processes timetable connections in chronological order of departure time $t_{dep}$:

1. **Connection Representation:** $C = (s_{dep}, s_{arr}, t_{dep}, t_{arr}, trip\_id)$.
2. **Initialization:**
   - Calculate earliest arrival time array $\tau[s] = \infty$ for all transit stops $s$.
   - For all stops $s_i$ reachable by walking from origin $O$:
     $$\tau[s_i] = t_{start} + T_{walk}(O, s_i) \quad \forall s_i \text{ where } T_{walk}(O, s_i) \le \text{max\_walk\_time}$$
3. **Scan Execution:**
   - Iterate through sorted connections where $t_{dep} \ge t_{start}$:
   - Let $penalty = 0$ if vehicle is same ($trip\_id_{previous} == trip\_id$), else $transfer\_penalty$.
   - If $\tau[s_{dep}] + penalty \le t_{dep}$:
     $$\tau[s_{arr}] = \min(\tau[s_{arr}], \; t_{arr})$$

### 4.3 Spatial Heatmap Evaluation Matrix
For a grid cell center $p(x, y)$:
$$T_{direct\_walk}(p) = T_{walk}(O, p)$$
$$T_{transit}(p) = \min_{s \in S_{reached}} \left[ (\tau[s] - t_{start}) + T_{walk}(s, p) \right]$$
$$T_{final}(p) = \min\left( T_{direct\_walk}(p), \; T_{transit}(p) \right)$$

Values are capped at $T_{cutoff} = 180 \text{ minutes}$.

---

## 5. Detailed Implementation Plan & Module Architecture

### File Structure
```
budapest_transit_heatmap/
│
├── main.py               # CLI entry point, orchestration logic
├── config.py             # Default constants, feed URLs, color palettes
├── downloader.py         # HTTP fetcher & cache manager for GTFS
├── gtfs_parser.py        # Date/calendar active service filtering & connection builder
├── csa_solver.py         # Vectorized Connection Scan Algorithm routing engine
├── grid_evaluator.py     # NumPy spatial grid evaluation matrix builder
└── renderer.py           # PyProj + PIL + Matplotlib OSM tile stitching & cartographic exporter
```

---

### Implementation Details by Module

#### Module 1: `config.py`
- Stores default bounding box for Budapest + Érd region: `[47.25, 18.80, 47.60, 19.30]`.
- Direct static feed URLs for BKK, MÁV, and Volánbusz.
- Standard EPSG projection codes (`4326` WGS84, `3857` Web Mercator).
- Tile server templates (e.g., CartoDB Positron / OSM Light).

#### Module 2: `downloader.py`
- `download_gtfs_feeds(cache_dir, max_age_days=7)`:
  - Checks if `.zip` files exist in `cache_dir` and are fresher than 7 days.
  - Uses `requests` with standard user-agents to stream-download missing or stale GTFS `.zip` archives.
  - Exposes in-memory `zipfile.ZipFile` handles to avoid unzipping millions of files to disk.

#### Module 3: `gtfs_parser.py`
- **Active Service Resolution:**
  - Reads `calendar.txt` and `calendar_dates.txt`.
  - Determines which `service_id` values are active for the targeted `--datetime` date (weekday / weekend / holiday overrides).
- **Bounding Box Spatial Filtering:**
  - Reads `stops.txt` from all feeds.
  - Filters out stops outside the bounding box + 10km buffer zone.
- **Connection Extraction:**
  - Reads `stop_times.txt` and `trips.txt`.
  - Converts GTFS time strings (`HH:MM:SS`, including $>24:00:00$ late night times) into integer departure and arrival seconds from midnight.
  - Builds a unified Pandas DataFrame of connections: `[s_dep, s_arr, t_dep, t_arr, trip_id]`.
  - Sorts connections chronologically by `t_dep`.

#### Module 4: `csa_solver.py`
- `solve_csa(connections_df, stops_df, start_lat, start_lon, departure_sec, walk_speed, max_walk_time, transfer_penalty)`:
  - Vectorizes initial walking times from `(start_lat, start_lon)` to all candidate stops using NumPy Haversine math.
  - Runs the pure-Python CSA loop over chronologically ordered connections.
  - Returns a dictionary / NumPy array of `{stop_id: earliest_arrival_seconds}`.

#### Module 5: `grid_evaluator.py`
- `compute_travel_time_grid(bbox, resolution_m, start_lat, start_lon, reached_stops, walk_speed, max_walk_time, max_cutoff)`:
  - Computes spatial grid matrix dimensions (width $\times$ height) in meters using `pyproj`.
  - Generates 2D arrays of grid cell coordinates (lat/lon).
  - Calculates direct walk time matrix from origin to every cell.
  - Computes transfer walk time from every reached transit stop to nearby grid cells within `max_walk_time`.
  - Minimizes across all options using `np.minimum`.

#### Module 6: `renderer.py`
- `render_map(grid_matrix, bbox, start_lat, start_lon, output_path)`:
  - Computes bounding box extent in Web Mercator projection (`EPSG:3857`).
  - Fetches and stitches OpenStreetMap/CartoDB background tiles for the bounding box.
  - Overlays the computed grid matrix using `matplotlib.pyplot.imshow`.
  - Applies dynamic colormap (`viridis_r` / `YlOrRd`) normalized to `[min_time, max_time_found_in_bbox]`.
  - Draws origin marker (star / pin), colorbar legend with minute ticks, scale bar, and metadata text box (date, start time, max duration).
  - Saves high-DPI `.png` output file.

#### Module 7: `main.py`
- Orchestrates CLI parameters using `argparse`.
- Handles logging output with step execution times.
- Runs the pipeline from GTFS downloading to final image rendering.
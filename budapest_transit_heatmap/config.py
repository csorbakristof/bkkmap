"""Default constants, feed URLs, projections and tile settings."""

# Budapest + Érd region: min_lat, min_lon, max_lat, max_lon
DEFAULT_BBOX = (47.25, 18.80, 47.60, 19.30)
BBOX_BUFFER_M = 10_000.0

# Static GTFS feeds. "required" feeds abort the run if they cannot be obtained;
# optional ones are skipped with a warning.
GTFS_FEEDS = {
    "bkk": {
        "url": "https://go.bkk.hu/api/static/v1/public-gtfs/budapest_gtfs.zip",
        "required": True,
    },
    # MÁV-csoport and Volánbusz publish GTFS only after registration, so there is no
    # download URL: place the archives in the cache dir as mav.zip / volan.zip.
    "mav": {"url": None, "required": False},
    "volan": {"url": None, "required": False},
}
FEED_MAX_AGE_DAYS = 7
HTTP_USER_AGENT = "budapest-transit-heatmap/0.1 (python-requests; personal non-bulk use)"

# OpenStreetMap road network for car routing (Geofabrik extract, refreshed daily upstream).
OSM_PBF_URL = "https://download.geofabrik.de/europe/hungary-latest.osm.pbf"
OSM_PBF_MAX_AGE_DAYS = 30
CAR_BBOX_BUFFER_M = 20_000.0

# Car-usable highway classes: (default speed limit km/h, share of it achieved on average).
# The share models signals, junctions and typical weekday-morning congestion.
ROAD_CLASSES = {
    "motorway": (130, 0.9),
    "motorway_link": (60, 0.75),
    "trunk": (110, 0.85),
    "trunk_link": (50, 0.7),
    "primary": (90, 0.75),
    "primary_link": (40, 0.7),
    "secondary": (80, 0.75),
    "secondary_link": (40, 0.7),
    "tertiary": (60, 0.7),
    "tertiary_link": (30, 0.65),
    "unclassified": (50, 0.65),
    "residential": (40, 0.6),
    "living_street": (20, 0.5),
}
# Classes the trip may not start/end on (you cannot park on a motorway).
NO_ACCESS_CLASSES = {"motorway", "motorway_link", "trunk", "trunk_link"}
# Symbolic maxspeed values (Hungarian defaults).
MAXSPEED_ZONES = {"HU:urban": 50, "HU:rural": 90, "HU:trunk": 110, "HU:motorway": 130,
                  "HU:living_street": 20, "walk": 7}
TRAFFIC_SIGNAL_PENALTY_S = 15.0
CAR_ORIGIN_SNAP_M = 500.0  # road nodes within this distance of the origin can be the start of the drive
CAR_PARK_SNAP_M = 500.0  # max straight-line walk from the parking node to a cell (farther: grid walking)
CAR_SNAP_NEIGHBORS = 8
DEFAULT_CAR_ACCESS_MIN = 2.0
DEFAULT_CAR_EGRESS_MIN = 5.0

EPSG_WGS84 = "EPSG:4326"
EPSG_WEB_MERCATOR = "EPSG:3857"

EARTH_RADIUS_M = 6_371_000.0
WALK_DETOUR_FACTOR = 1.25

# Max walking time between two nearby stops for transfers inside the CSA (minutes).
MAX_TRANSFER_WALK_MIN = 5.0

# OSM standard tiles (CARTO basemaps now require an API key). Tiles are cached on
# disk per the OSM tile usage policy and desaturated before use.
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_SIZE = 256
TILE_ATTRIBUTION = "© OpenStreetMap contributors"
BASEMAP_DESATURATION = 0.75  # 0 = original colors, 1 = grayscale
TARGET_MAP_WIDTH_PX = 2000

COLORMAP = "turbo"
OVERLAY_ALPHA = 0.275
CONTOUR_INTERVAL_MIN = 60.0  # isochrone lines at whole hours
OUTPUT_DPI = 200  # at the default width; scaled with --width-px so text keeps its relative size

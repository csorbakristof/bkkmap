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
    # MÁV-csoport publishes GTFS only after registration
    # (https://www.mavcsoport.hu/gtfs-igenybejelento). Put the received zips into
    # the cache dir as mav.zip / volanbusz.zip, or pass --extra-feed.
    "mav": {"url": "https://gtfs.menetbrand.com/mav/gtfs.zip", "required": False},
    "volanbusz": {"url": "https://gtfs.menetbrand.com/volanbusz/gtfs.zip", "required": False},
}
FEED_MAX_AGE_DAYS = 7
HTTP_USER_AGENT = "budapest-transit-heatmap/0.1 (python-requests; personal non-bulk use)"

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
OVERLAY_ALPHA = 0.55
OUTPUT_DPI = 200  # at the default width; scaled with --width-px so text keeps its relative size

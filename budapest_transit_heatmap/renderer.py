"""Basemap (OSM data or OSM tiles) and cartographic heatmap export."""
import io
import logging
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import requests  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402
from matplotlib.transforms import Affine2D, ScaledTranslation  # noqa: E402
from PIL import Image  # noqa: E402
from pyproj import Transformer  # noqa: E402

from basemap import draw_osm_basemap, draw_place_labels, meters_per_pixel  # noqa: E402
from config import (BASEMAP_DESATURATION, COLORMAP, EPSG_WEB_MERCATOR, EPSG_WGS84, HTTP_USER_AGENT, OUTPUT_DPI,  # noqa: E402
                    CONTOUR_INTERVAL_MIN, OVERLAY_ALPHA, TARGET_MAP_WIDTH_PX, TILE_ATTRIBUTION, TILE_SIZE, TILE_URL)

log = logging.getLogger(__name__)

MERC_HALF = 20037508.342789244  # half the Web Mercator world width in meters
_to_merc = Transformer.from_crs(EPSG_WGS84, EPSG_WEB_MERCATOR, always_xy=True)
_to_wgs = Transformer.from_crs(EPSG_WEB_MERCATOR, EPSG_WGS84, always_xy=True)


def _zoom_for(extent, target_px):
    world_frac = (extent[1] - extent[0]) / (2 * MERC_HALF)
    # Allow up to ~15% upscaling of tiles before moving to the next zoom (4x more tiles).
    return int(min(18, max(1, math.ceil(math.log2(target_px / (world_frac * TILE_SIZE)) - 0.2))))


def _tile_range(extent, z):
    n = 2 ** z
    to_tx = lambda x: int(math.floor((x + MERC_HALF) / (2 * MERC_HALF) * n))  # noqa: E731
    to_ty = lambda y: int(math.floor((MERC_HALF - y) / (2 * MERC_HALF) * n))  # noqa: E731
    return to_tx(extent[0]), to_tx(extent[1]), to_ty(extent[3]), to_ty(extent[2])


def _get_tile(session, z, x, y, tile_cache):
    path = tile_cache / str(z) / str(x) / f"{y}.png" if tile_cache else None
    if path and path.exists():
        return Image.open(path).convert("RGB")
    url = TILE_URL.format(z=z, x=x, y=y)
    r = session.get(url, timeout=30)
    r.raise_for_status()
    if not r.headers.get("Content-Type", "").startswith("image/"):
        raise ValueError(f"tile server returned {r.headers.get('Content-Type')!r} instead of an image")
    img = Image.open(io.BytesIO(r.content)).convert("RGB")  # fails on corrupt data before caching
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    return img


def fetch_basemap(extent, tile_cache=None, target_px=TARGET_MAP_WIDTH_PX):
    """Stitched basemap covering `extent` (3857). Returns (PIL image, image extent) or None."""
    z = _zoom_for(extent, target_px)
    tx0, tx1, ty0, ty1 = _tile_range(extent, z)
    count = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
    log.info("Basemap: zoom %d, %d tiles", z, count)
    img = Image.new("RGB", ((tx1 - tx0 + 1) * TILE_SIZE, (ty1 - ty0 + 1) * TILE_SIZE), "white")
    session = requests.Session()
    session.headers["User-Agent"] = HTTP_USER_AGENT
    try:
        for x in range(tx0, tx1 + 1):
            for y in range(ty0, ty1 + 1):
                img.paste(_get_tile(session, z, x, y, tile_cache), ((x - tx0) * TILE_SIZE, (y - ty0) * TILE_SIZE))
    except Exception as exc:  # noqa: BLE001
        log.warning("Basemap tiles unavailable (%s); rendering without background", exc)
        return None
    gray = img.convert("L").convert("RGB")
    img = Image.blend(img, gray, BASEMAP_DESATURATION)
    tile_m = 2 * MERC_HALF / 2 ** z
    img_extent = (tx0 * tile_m - MERC_HALF, (tx1 + 1) * tile_m - MERC_HALF,
                  MERC_HALF - (ty1 + 1) * tile_m, MERC_HALF - ty0 * tile_m)
    return img, img_extent


def _draw_flag(ax, fig, x, y, height_pt=44):
    """Flag whose pole foot sits on data point (x, y). Sized in points, so it scales with the figure."""
    h = height_pt
    # Shape coordinates are in points relative to the pole foot.
    pole = [(-1.2, 0), (1.2, 0), (1.2, h), (-1.2, h)]
    banner = [(1.2, h), (h * 0.62, h * 0.92), (h * 0.5, h * 0.78), (h * 0.62, h * 0.64), (1.2, h * 0.56)]
    trans = (Affine2D().scale(1 / 72) + fig.dpi_scale_trans + ScaledTranslation(x, y, ax.transData))
    artists = [ax.add_patch(Polygon(pole, closed=True, facecolor="#222222", edgecolor="white", linewidth=1.2,
                                    transform=trans, zorder=8, clip_on=False)),
               ax.add_patch(Polygon(banner, closed=True, facecolor="#e60000", edgecolor="white", linewidth=1.2,
                                    transform=trans, zorder=9, clip_on=False))]
    ax.plot(x, y, marker="o", markersize=5, color="#222222", markeredgecolor="white", markeredgewidth=1,
            zorder=8)
    return artists


def _nice_length(max_m):
    exp = 10 ** math.floor(math.log10(max_m))
    for m in (5, 2, 1):
        if m * exp <= max_m:
            return m * exp
    return exp


def _draw_scale_bar(ax, extent, center_lat):
    width_ground = (extent[1] - extent[0]) * math.cos(math.radians(center_lat))
    length_m = _nice_length(width_ground / 5)
    length_merc = length_m / math.cos(math.radians(center_lat))
    x0 = extent[0] + 0.04 * (extent[1] - extent[0])
    y0 = extent[2] + 0.04 * (extent[3] - extent[2])
    h = 0.008 * (extent[3] - extent[2])
    ax.fill_between([x0, x0 + length_merc], y0, y0 + h, color="black", zorder=6)
    ax.fill_between([x0 + length_merc / 2, x0 + length_merc], y0, y0 + h, color="white", edgecolor="black",
                    linewidth=0.8, zorder=7)
    label = f"{length_m / 1000:g} km" if length_m >= 1000 else f"{length_m:g} m"
    return ax.text(x0 + length_merc / 2, y0 + 2 * h, label, ha="center", va="bottom", fontsize=9, zorder=7,
            bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=1))


def render_map(grid_matrix, extent, bbox, start_lat, start_lon, output_path, metadata, tile_cache=None,
               width_px=TARGET_MAP_WIDTH_PX, overlay_alpha=OVERLAY_ALPHA, contour_interval=CONTOUR_INTERVAL_MIN,
               basemap="tiles", osm_features=None, roads=None, label_scale=1.0):
    """Write the heatmap PNG. `extent` is the grid's (left, right, bottom, top) in EPSG:3857.

    basemap: "osm" draws the background and place labels from osm_features/roads,
    "tiles" uses OSM raster tiles, "none" leaves it blank.
    """
    vmin, vmax = float(np.min(grid_matrix)), float(np.max(grid_matrix))
    if vmax - vmin < 1e-6:
        vmax = vmin + 1.0

    aspect = (extent[3] - extent[2]) / (extent[1] - extent[0])
    fig_w = TARGET_MAP_WIDTH_PX / OUTPUT_DPI
    dpi = OUTPUT_DPI * width_px / TARGET_MAP_WIDTH_PX
    fig, ax = plt.subplots(figsize=(fig_w * 1.12, fig_w * aspect))
    fig.subplots_adjust(left=0.01, right=0.88, top=0.99, bottom=0.01)

    mpp = meters_per_pixel(extent, width_px, (bbox[0] + bbox[2]) / 2)
    if basemap == "osm":
        draw_osm_basemap(ax, osm_features, roads, extent, mpp)
    elif basemap == "tiles":
        tiles = fetch_basemap(extent, tile_cache, width_px)
        if tiles is not None:
            img, img_extent = tiles
            ax.imshow(np.asarray(img), extent=img_extent, origin="upper", interpolation="bilinear", zorder=0)

    norm = Normalize(vmin=vmin, vmax=vmax)
    im = ax.imshow(grid_matrix, extent=extent, origin="upper", cmap=COLORMAP, norm=norm,
                   alpha=overlay_alpha, interpolation="nearest", zorder=1)

    # Isochrone contour lines help read the gradient.
    levels = np.arange(contour_interval, vmax, contour_interval)
    if len(levels):
        xs = np.linspace(extent[0], extent[1], grid_matrix.shape[1])
        ys = np.linspace(extent[3], extent[2], grid_matrix.shape[0])
        cs = ax.contour(xs, ys, grid_matrix, levels=levels, colors="black", linewidths=0.4, alpha=0.5, zorder=2)
        ax.clabel(cs, fmt="%d'", fontsize=6, inline=True)

    sx, sy = _to_merc.transform(start_lon, start_lat)
    flag = _draw_flag(ax, fig, sx, sy)

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xticks([])
    ax.set_yticks([])

    cax = fig.add_axes([0.895, 0.1, 0.025, 0.8])
    cb = fig.colorbar(im, cax=cax)
    cb.solids.set_alpha(1.0)
    cb.locator = MaxNLocator(nbins=10, integer=True)
    cb.update_ticks()
    cb.set_label("Travel time (minutes)")

    scale_label = _draw_scale_bar(ax, extent, (bbox[0] + bbox[2]) / 2)

    info = ax.text(0.015, 0.985, "\n".join(metadata), transform=ax.transAxes, ha="left", va="top", fontsize=8,
                   zorder=9, bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"))
    credit = ax.text(0.995, 0.005, TILE_ATTRIBUTION, transform=ax.transAxes, ha="right", va="bottom", fontsize=6,
                     zorder=9, bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=1))

    if basemap == "osm":
        draw_place_labels(ax, osm_features, extent, mpp, avoid=[info, credit, scale_label, *flag], scale=label_scale)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi)
    plt.close(fig)
    log.info("Map written to %s", output_path)

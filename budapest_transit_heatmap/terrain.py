"""Hillshade (terrain relief) from AWS Terrain Tiles (Terrarium PNG elevation tiles, cached on disk)."""
import io
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from scipy.ndimage import gaussian_filter

from config import (HILLSHADE_ALTITUDE_DEG, HILLSHADE_AZIMUTH_DEG, HILLSHADE_DARK, HILLSHADE_EXAGGERATION,
                    HILLSHADE_LIGHT, HTTP_USER_AGENT, TERRAIN_TILE_URL, TILE_SIZE)

log = logging.getLogger(__name__)

MERC_HALF = 20037508.342789244


def _tile(cache_dir, z, x, y):
    path = Path(cache_dir) / "terrain" / str(z) / str(x) / f"{y}.png"
    if not path.exists():
        r = requests.get(TERRAIN_TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": HTTP_USER_AGENT}, timeout=60)
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768  # Terrarium encoding, meters


def load_hillshade(cache_dir, extent, mpp, center_lat):
    """RGBA hillshade image covering (at least) extent, and its Web Mercator extent (left, right, bottom, top)."""
    # Tile resolution about equal to or finer than the output (~1 elevation pixel per output pixel).
    z = int(min(12, max(3, math.ceil(math.log2(156543.03 * math.cos(math.radians(center_lat)) / mpp)))))
    ts = 2 * MERC_HALF / 2 ** z
    x0, x1 = int((extent[0] + MERC_HALF) // ts), int((extent[1] + MERC_HALF) // ts)
    y0, y1 = int((MERC_HALF - extent[3]) // ts), int((MERC_HALF - extent[2]) // ts)
    coords = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    log.info("Terrain: %d elevation tiles at zoom %d", len(coords), z)
    with ThreadPoolExecutor(8) as pool:
        tiles = list(pool.map(lambda c: _tile(cache_dir, z, *c), coords))
    n = x1 - x0 + 1
    dem = np.vstack([np.hstack(tiles[r * n:(r + 1) * n]) for r in range((y1 - y0) + 1)])
    img_extent = (x0 * ts - MERC_HALF, (x1 + 1) * ts - MERC_HALF, MERC_HALF - (y1 + 1) * ts, MERC_HALF - y0 * ts)

    cell = ts / TILE_SIZE * math.cos(math.radians(center_lat))  # ground meters per elevation pixel
    dem = gaussian_filter(np.maximum(dem, 0), 1.0) * HILLSHADE_EXAGGERATION
    dzdy, dzdx = np.gradient(dem, cell)  # rows run north -> south
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(-dzdx, dzdy)
    az, alt = math.radians(360 - HILLSHADE_AZIMUTH_DEG + 90), math.radians(HILLSHADE_ALTITUDE_DEG)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    delta = shade - math.sin(alt)  # 0 on flat ground, negative in shadow, positive on lit slopes

    rgba = np.zeros(delta.shape + (4,), np.float32)
    shadow = delta < 0
    rgba[shadow, :3] = HILLSHADE_DARK
    rgba[~shadow, :3] = HILLSHADE_LIGHT
    rgba[..., 3] = np.clip(np.abs(delta) * np.where(shadow, 1.8, 1.2), 0, 0.75)
    return rgba, img_extent

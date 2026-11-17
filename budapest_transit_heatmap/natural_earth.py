"""Background for the area outside Hungary on country-scale maps, from Natural Earth (public domain).

The OSM extract only covers Hungary, so rivers, lakes, borders and larger cities of the neighbouring
countries come from Natural Earth GeoJSON files (a few MB, cached). Everything inside Hungary is dropped
because the OSM data already draws it in far more detail.
"""
import json
import logging
from pathlib import Path

import numpy as np
from matplotlib.path import Path as MplPath

from config import HU_EXONYMS, NE_BASE_URL, NE_FILES
from downloader import _download

log = logging.getLogger(__name__)

MARGIN_DEG = 0.5


def _load(cache_dir, name):
    dest = Path(cache_dir) / "naturalearth" / f"{name}.geojson"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        log.info("Natural Earth: downloading %s", name)
        _download(f"{NE_BASE_URL}/{name}.geojson", dest, validate=lambda p: p.stat().st_size > 1000)
    with open(dest, encoding="utf8") as f:
        return json.load(f)["features"]


def _rings(geom):
    """Exterior rings (Nx2 lon/lat arrays) of a Polygon / MultiPolygon geometry."""
    if geom["type"] == "Polygon":
        return [np.asarray(geom["coordinates"][0], float)]
    if geom["type"] == "MultiPolygon":
        return [np.asarray(p[0], float) for p in geom["coordinates"]]
    return []


def _lines(geom):
    if geom["type"] == "LineString":
        return [np.asarray(geom["coordinates"], float)]
    if geom["type"] == "MultiLineString":
        return [np.asarray(c, float) for c in geom["coordinates"]]
    return []


def _runs(line, outside):
    """Pieces of `line` made of consecutive vertices flagged `outside` (at least two vertices each)."""
    out, start = [], None
    for i, flag in enumerate(np.r_[outside, False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= 2:
                out.append(line[start:i])
            start = None
    return out


def load_foreign_background(cache_dir, bbox):
    """Rivers, lakes, borders and places outside Hungary within bbox (min lat, min lon, max lat, max lon).

    Returns a dict: rivers [(lonlat Nx2, linewidth pt)], lakes [lonlat Nx2], borders [lonlat Nx2] and the
    place_* arrays (name, kind index into osm_features.PLACE_KINDS, pop, lat, lon) .
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    lo = np.array([min_lon - MARGIN_DEG, min_lat - MARGIN_DEG])
    hi = np.array([max_lon + MARGIN_DEG, max_lat + MARGIN_DEG])

    def near(pts):
        return bool(np.all(pts.max(axis=0) >= lo) and np.all(pts.min(axis=0) <= hi))

    hungary = MplPath.make_compound_path(*[
        MplPath(r) for f in _load(cache_dir, NE_FILES["countries"]) if f["properties"]["ADM0_A3"] == "HUN"
        for r in _rings(f["geometry"])])

    def outside_hu(pts):
        return ~hungary.contains_points(pts)

    rivers = []
    for key, scale_width in (("rivers", None), ("rivers_europe", 0.3)):
        for f in _load(cache_dir, NE_FILES[key]):
            rank = f["properties"].get("scalerank") or 12
            width = scale_width or (0.9 if rank <= 4 else 0.6 if rank <= 7 else 0.4)
            for line in _lines(f["geometry"]):
                if near(line):
                    rivers += [(r, width) for r in _runs(line, outside_hu(line))]

    lakes = []
    for key in ("lakes", "lakes_europe"):
        for f in _load(cache_dir, NE_FILES[key]):
            for ring in _rings(f["geometry"]):
                if near(ring) and not hungary.contains_point(ring.mean(axis=0)):
                    lakes.append(ring)

    borders = []
    for f in _load(cache_dir, NE_FILES["borders"]):
        p = f["properties"]
        if "HUN" in (p.get("ADM0_A3_L"), p.get("ADM0_A3_R")):
            continue  # Hungary's own border is drawn from OSM
        for line in _lines(f["geometry"]):
            if near(line):
                borders += _runs(line, outside_hu(line))

    places = []
    for f in _load(cache_dir, NE_FILES["places"]):
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        pop = int(p.get("pop_max") or 0)
        capital = bool(p.get("adm0cap"))
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon) or p.get("iso_a2") == "HU":
            continue
        if hungary.contains_point((lon, lat)) or not (capital or pop >= 50_000):
            continue
        kind = 0 if capital else 1 if pop >= 250_000 else 2
        name = HU_EXONYMS.get(p["name"]) or p.get("namepar") or p["name"]
        places.append((name, kind, pop, lat, lon))
    log.info("Natural Earth: %d rivers, %d lakes, %d borders, %d places outside Hungary",
             len(rivers), len(lakes), len(borders), len(places))
    return {
        "rivers": rivers, "lakes": lakes, "borders": borders,
        "place_name": np.array([p[0] for p in places], dtype=str),
        "place_kind": np.array([p[1] for p in places], np.int8),
        "place_pop": np.array([p[2] for p in places], np.int64),
        "place_lat": np.array([p[3] for p in places]), "place_lon": np.array([p[4] for p in places]),
    }

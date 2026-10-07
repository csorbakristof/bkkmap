"""Label-free basemap drawn from OpenStreetMap data, plus self-placed place-name labels."""
import math

import matplotlib.patheffects as pe
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from pyproj import Transformer

from config import (BASEMAP_COLORS, EPSG_WEB_MERCATOR, EPSG_WGS84, LABEL_FONT_PT, LABEL_MAX_MPP,
                    LABEL_MIN_POP_PER_MPP, PLAIN_SUBURB_MAX_MPP, ROAD_STYLE)
from osm_features import PLACE_KINDS

_to_merc = Transformer.from_crs(EPSG_WGS84, EPSG_WEB_MERCATOR, always_xy=True)

# (layer, color key, linewidth pt, max meters/pixel, zorder) for line layers
_LINE_STYLE = [
    ("border6", "border", 0.35, 1e9, 0.55),
    ("canal", "water", 0.3, 50, 0.3),
    ("river", "water", 0.7, 1e9, 0.31),
    ("rail", "rail", 0.35, 1e9, 0.5),
    ("border2", "border", 1.0, 1e9, 0.56),
]


def meters_per_pixel(extent, width_px, center_lat):
    return (extent[1] - extent[0]) * math.cos(math.radians(center_lat)) / width_px


def _features_in_extent(lat, lon, off, extent, min_size_m=0.0):
    """Mercator coordinates and offsets of the features intersecting extent (and at least min_size_m wide)."""
    x, y = _to_merc.transform(lon.astype(np.float64), lat.astype(np.float64))
    starts = off[:-1]
    if not len(starts):
        return x, y, np.zeros(0, int)
    x0, x1 = np.minimum.reduceat(x, starts), np.maximum.reduceat(x, starts)
    y0, y1 = np.minimum.reduceat(y, starts), np.maximum.reduceat(y, starts)
    keep = (x1 >= extent[0]) & (x0 <= extent[1]) & (y1 >= extent[2]) & (y0 <= extent[3])
    if min_size_m > 0:
        keep &= np.maximum(x1 - x0, y1 - y0) >= min_size_m
    return x, y, np.flatnonzero(keep)


def _polylines(feat, layer, extent, min_size_m=0.0):
    off = feat[f"{layer}_off"]
    x, y, idx = _features_in_extent(feat[f"{layer}_lat"], feat[f"{layer}_lon"], off, extent, min_size_m)
    return [np.column_stack((x[off[i]:off[i + 1]], y[off[i]:off[i + 1]])) for i in idx], idx


def _draw_polygons(ax, feat, layer, extent, mpp, color, zorder):
    # Rings narrower than ~2 pixels are invisible; skipping them keeps rendering fast.
    rings, idx = _polylines(feat, layer, extent, min_size_m=2 * mpp / math.cos(math.radians(47)))
    if not rings:
        return
    inner = feat[f"{layer}_inner"][idx]
    verts, codes = [], []
    for ring, is_inner in zip(rings, inner):
        # Nonzero fill: outer rings counter-clockwise, holes clockwise.
        area = np.sum(ring[:-1, 0] * ring[1:, 1] - ring[1:, 0] * ring[:-1, 1])
        if (area > 0) == bool(is_inner):
            ring = ring[::-1]
        verts.append(ring)
        c = np.full(len(ring), MplPath.LINETO, np.uint8)
        c[0], c[-1] = MplPath.MOVETO, MplPath.CLOSEPOLY
        codes.append(c)
    path = MplPath(np.concatenate(verts), np.concatenate(codes))
    ax.add_patch(PathPatch(path, facecolor=color, edgecolor="none", zorder=zorder))


def draw_osm_basemap(ax, feat, roads, extent, mpp):
    """Background, built-up areas, water, roads, railways and borders (no labels)."""
    ax.set_facecolor(BASEMAP_COLORS["land"])
    _draw_polygons(ax, feat, "builtup", extent, mpp, BASEMAP_COLORS["builtup"], 0.1)
    _draw_polygons(ax, feat, "water", extent, mpp, BASEMAP_COLORS["water"], 0.2)

    if roads is not None:
        from osm_roads import CLASS_NAMES
        a, b = roads.edge_src, roads.edge_dst
        once = (a < b) | ~np.isin(a.astype(np.int64) * len(roads.node_lat) + b,
                                  b.astype(np.int64) * len(roads.node_lat) + a)  # one copy of two-way edges
        nx, ny = _to_merc.transform(roads.node_lon, roads.node_lat)
        for cls_name, (color, width, max_mpp, z) in sorted(ROAD_STYLE.items(), key=lambda kv: kv[1][3]):
            if mpp > max_mpp:
                continue
            sel = np.flatnonzero(once & (roads.edge_class == CLASS_NAMES.index(cls_name)))
            if not len(sel):
                continue
            segs = np.stack([np.column_stack((nx[a[sel]], ny[a[sel]])),
                             np.column_stack((nx[b[sel]], ny[b[sel]]))], axis=1)
            ax.add_collection(LineCollection(segs, colors=BASEMAP_COLORS[color], linewidths=width,
                                             capstyle="round", zorder=z))

    for layer, color, width, max_mpp, z in _LINE_STYLE:
        if mpp > max_mpp:
            continue
        lines, _ = _polylines(feat, layer, extent)
        if lines:
            style = dict(linestyles=(0, (4, 2)), linewidths=width) if layer == "border6" else dict(linewidths=width)
            ax.add_collection(LineCollection(lines, colors=BASEMAP_COLORS[color], capstyle="round",
                                             zorder=z, **style))


def draw_place_labels(ax, feat, extent, mpp, avoid=(), scale=1.0):
    """Place names, most important first; a label is skipped when it would overlap an earlier one.

    Which kinds are eligible and their minimum population depend on the map scale, so a
    country map shows cities and larger towns while a city map also shows villages (and, zoomed in
    further, suburbs). Labels never extend past the map frame.
    """
    fig = ax.figure
    renderer = fig.canvas.get_renderer()
    taken = [a.get_window_extent(renderer) for a in avoid]
    frame = ax.get_window_extent(renderer)
    x, y = _to_merc.transform(feat["place_lon"], feat["place_lat"])
    inside = (x > extent[0]) & (x < extent[1]) & (y > extent[2]) & (y < extent[3])
    halo = [pe.withStroke(linewidth=2.2 * scale, foreground="white")]
    for i in np.flatnonzero(inside):  # cache order: by kind, then population descending
        kind = PLACE_KINDS[feat["place_kind"][i]]
        if mpp > LABEL_MAX_MPP[kind] or feat["place_pop"][i] < LABEL_MIN_POP_PER_MPP[kind] * mpp:
            continue
        # Lesser-known suburbs (no wikidata/wikipedia link in OSM) only on closer-in maps, with more spacing.
        plain = kind == "suburb" and not feat["place_notable"][i]
        if plain and mpp > PLAIN_SUBURB_MAX_MPP:
            continue
        size = LABEL_FONT_PT[kind] * scale
        t = ax.text(x[i], y[i], feat["place_name"][i], ha="center", va="center", fontsize=size,
                    fontweight="bold" if kind in ("capital", "city") else "normal",
                    fontstyle="italic" if kind == "suburb" else "normal",
                    color=BASEMAP_COLORS["label"], path_effects=halo, zorder=4, clip_on=True)
        text_box = t.get_window_extent(renderer)
        pad = (1.0 if plain else 0.6) * text_box.height
        box = text_box.expanded((text_box.width + 2 * pad) / text_box.width,
                                (text_box.height + 2 * pad) / text_box.height)
        # Centered on the place first; if that collides (e.g. with the origin flag), try beside it.
        px, py = ax.transData.transform((x[i], y[i]))
        dw, dh = 0.5 * box.width + 0.3 * box.height, box.height
        for dx, dy in ((0, 0), (0, -dh), (0, dh), (dw, 0), (-dw, 0)):
            moved = box.translated(dx, dy)
            tb = text_box.translated(dx, dy)
            in_frame = frame.x0 <= tb.x0 and tb.x1 <= frame.x1 and frame.y0 <= tb.y0 and tb.y1 <= frame.y1
            if in_frame and not any(moved.overlaps(o) for o in taken):
                t.set_position(ax.transData.inverted().transform((px + dx, py + dy)))
                taken.append(moved)
                break
        else:
            t.remove()

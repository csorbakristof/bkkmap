"""Label-free basemap features and place names from an OpenStreetMap .osm.pbf extract.

Parsed once per extract into flat arrays (cached as .npz): line layers (rivers,
railways, borders), polygon rings (water, built-up areas) and named places.
Roads come from the car road graph (osm_roads.py), which is cached separately.
"""
import logging
import re
from array import array
from itertools import accumulate
from pathlib import Path

import numpy as np

from osm_pbf import Block, dense_with_key, fields, iter_blocks, packed_list, zigzag_list

log = logging.getLogger(__name__)

FEATURES_CACHE_VERSION = 1
LINE_LAYERS = ("river", "canal", "rail", "border2", "border6")
POLYGON_LAYERS = ("water", "builtup")
PLACE_KINDS = ("capital", "city", "town", "village", "suburb")

_WATER_TAGS = {(b"natural", b"water"), (b"landuse", b"reservoir"), (b"landuse", b"basin"),
               (b"waterway", b"riverbank")}
_BUILTUP = {b"residential", b"commercial", b"industrial", b"retail"}
_PLACES = {b"city": 1, b"town": 2, b"village": 3, b"suburb": 4}
_WAY_KEYS = (b"natural", b"landuse", b"waterway", b"railway", b"water")
_DIGITS = re.compile(rb"\d+")


def _is_water(tags):
    return any(tags.get(k) == v for k, v in _WATER_TAGS) or b"water" in tags


def _line_layer(tags):
    ww = tags.get(b"waterway")
    if ww == b"river":
        return "river"
    if ww == b"canal":
        return "canal"
    if tags.get(b"railway") == b"rail" and b"service" not in tags:  # skip sidings, yards, spurs
        return "rail"
    return None


def _polygon_layer(tags):
    if _is_water(tags):
        return "water"
    if tags.get(b"landuse") in _BUILTUP:
        return "builtup"
    return None


def _decode_way(way):
    wid, keys, vals, refs = 0, b"", b"", b""
    for fn, val in fields(way):
        if fn == 1:
            wid = val
        elif fn == 2:
            keys = val
        elif fn == 3:
            vals = val
        elif fn == 8:
            refs = val
    return wid, keys, vals, refs


def _relation_pass(path):
    """Way ids of water multipolygons (outer/inner) and of national/county border relations."""
    water, borders = [], {"border2": set(), "border6": set()}
    for data in iter_blocks(path):
        block = Block(data)
        strings = block.strings
        for rel in block.relations():
            keys = vals = roles = memids = types = b""
            for fn, val in fields(rel):
                if fn == 2:
                    keys = val
                elif fn == 3:
                    vals = val
                elif fn == 8:
                    roles = val
                elif fn == 9:
                    memids = val
                elif fn == 10:
                    types = val
            tags = {strings[k]: strings[v] for k, v in zip(packed_list(keys), packed_list(vals))}
            if not tags:
                continue
            ids = list(accumulate(zigzag_list(packed_list(memids))))
            members = [(m, strings[r]) for m, r, t in zip(ids, packed_list(roles), packed_list(types)) if t == 1]
            if tags.get(b"type") == b"multipolygon" and _is_water(tags):
                water.append(([m for m, r in members if r != b"inner"], [m for m, r in members if r == b"inner"]))
            elif tags.get(b"boundary") == b"administrative" and tags.get(b"admin_level") in (b"2", b"6"):
                borders["border" + tags[b"admin_level"].decode()].update(m for m, _ in members)
    return water, borders


def _assemble_rings(way_ids, way_refs):
    """Join way node sequences end to end into closed rings (lists of node ids)."""
    pieces = [list(way_refs[w]) for w in way_ids if w in way_refs]
    rings = []
    while pieces:
        ring = pieces.pop()
        while ring[0] != ring[-1]:
            for i, p in enumerate(pieces):
                if p[0] == ring[-1]:
                    ring += p[1:]
                elif p[-1] == ring[-1]:
                    ring += p[::-1][1:]
                elif p[-1] == ring[0]:
                    ring = p[:-1] + ring
                elif p[0] == ring[0]:
                    ring = p[::-1][:-1] + ring
                else:
                    continue
                pieces.pop(i)
                break
            else:
                break  # cannot be closed (members missing from the extract)
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def _parse_pbf(path):
    water_rels, border_ids = _relation_pass(path)
    member_ways = {w for outer, inner in water_rels for w in outer + inner}
    border_ways = border_ids["border2"] | border_ids["border6"]
    wanted = member_ways | border_ways
    log.info("OSM basemap: %d water multipolygons, %d border ways", len(water_rels), len(border_ways))

    lines = {k: [] for k in LINE_LAYERS}  # lists of node-id lists
    rings = {k: [] for k in POLYGON_LAYERS}  # lists of (node-id list, is_inner)
    way_refs = {}
    for data in iter_blocks(path):
        block = Block(data)
        strings = block.strings
        key_idx = [block.string_index(k) for k in _WAY_KEYS]
        quick = {bytes([i]) for i in key_idx if i is not None and i < 128}
        has_slow_key = any(i is not None and i >= 128 for i in key_idx)
        for way in block.ways():
            wid, keys, vals, refs_buf = _decode_way(way)
            if wid not in wanted and not has_slow_key and not any(q in keys for q in quick):
                continue
            tags = {strings[k]: strings[v] for k, v in zip(packed_list(keys), packed_list(vals))}
            line, poly = _line_layer(tags), None
            if line is None:
                poly = _polygon_layer(tags)
            if line is None and poly is None and wid not in wanted:
                continue
            refs = list(accumulate(zigzag_list(packed_list(refs_buf))))
            if len(refs) < 2:
                continue
            if wid in wanted:
                way_refs[wid] = refs
            if line:
                lines[line].append(refs)
            elif poly and refs[0] == refs[-1] and len(refs) >= 4:
                rings[poly].append((refs, False))

    for layer, ids in border_ids.items():
        lines[layer] = [way_refs[w] for w in ids if w in way_refs]
    for outer, inner in water_rels:
        rings["water"] += [(r, False) for r in _assemble_rings(outer, way_refs)]
        rings["water"] += [(r, True) for r in _assemble_rings(inner, way_refs)]

    # Node coordinates and named places.
    all_ids = [lines[k] for k in LINE_LAYERS] + [[r for r, _ in rings[k]] for k in POLYGON_LAYERS]
    node_ids = np.unique(np.fromiter((n for group in all_ids for seq in group for n in seq), np.int64))
    lat = np.full(len(node_ids), np.nan)
    lon = np.full(len(node_ids), np.nan)
    places = []
    for data in iter_blocks(path):
        block = Block(data)
        place_key = block.string_index(b"place")
        for ids, nlat, nlon, kv in block.dense_nodes():
            pos = np.clip(np.searchsorted(node_ids, ids), 0, len(node_ids) - 1)
            hit = node_ids[pos] == ids
            lat[pos[hit]] = nlat[hit]
            lon[pos[hit]] = nlon[hit]
            for i, tags in dense_with_key(kv, place_key, block.strings).items():
                kind = _PLACES.get(tags.get(b"place"))
                name = tags.get(b"name")
                if kind is None or not name:
                    continue
                if tags.get(b"capital") in (b"yes", b"2") and kind == 1:
                    kind = 0
                digits = _DIGITS.findall(tags.get(b"population", b"").replace(b" ", b""))
                places.append((name.decode(errors="replace"), kind, int(digits[0]) if digits else 0,
                               float(nlat[i]), float(nlon[i])))

    out = {}

    def coords(seqs, prefix, extra=None):
        flat = np.fromiter((n for s in seqs for n in s), np.int64)
        idx = np.searchsorted(node_ids, flat)
        offsets = np.r_[0, np.cumsum([len(s) for s in seqs])].astype(np.int64)
        f_lat, f_lon = lat[idx], lon[idx]
        # Drop features with nodes missing from the extract.
        bad = np.add.reduceat(~np.isfinite(f_lat), offsets[:-1]) > 0 if len(seqs) else np.zeros(0, bool)
        keep = np.repeat(~bad, np.diff(offsets))
        out[f"{prefix}_lat"] = f_lat[keep].astype(np.float32)
        out[f"{prefix}_lon"] = f_lon[keep].astype(np.float32)
        out[f"{prefix}_off"] = np.r_[0, np.cumsum(np.diff(offsets)[~bad])].astype(np.int64)
        if extra is not None:
            out[f"{prefix}_inner"] = np.asarray(extra, bool)[~bad]

    for k in LINE_LAYERS:
        coords(lines[k], k)
    for k in POLYGON_LAYERS:
        coords([r for r, _ in rings[k]], k, [inner for _, inner in rings[k]])
    places.sort(key=lambda p: (p[1], -p[2]))
    out["place_name"] = np.array([p[0] for p in places], dtype=str)
    out["place_kind"] = np.array([p[1] for p in places], np.int8)
    out["place_pop"] = np.array([p[2] for p in places], np.int64)
    out["place_lat"] = np.array([p[3] for p in places])
    out["place_lon"] = np.array([p[4] for p in places])
    log.info("OSM basemap: %s; %d places", ", ".join(f"{len(out[k + '_off']) - 1} {k}"
                                                   for k in LINE_LAYERS + POLYGON_LAYERS), len(places))
    return out


def load_basemap_features(pbf_path, cache_dir):
    """Basemap layers and places of the whole extract (cached), as a dict of arrays."""
    pbf_path = Path(pbf_path)
    stamp = int(pbf_path.stat().st_mtime)
    base = pbf_path.stem.split(".")[0]
    cache = Path(cache_dir) / "parsed" / f"basemap_{base}_{stamp}_v{FEATURES_CACHE_VERSION}.npz"
    if cache.exists():
        log.info("OSM basemap: loading parsed features from %s", cache.name)
        return dict(np.load(cache, allow_pickle=False))
    log.info("OSM basemap: parsing %s (one-off)", pbf_path.name)
    data = _parse_pbf(pbf_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    for old in cache.parent.glob(f"basemap_{base}_*.npz"):
        old.unlink()
    np.savez_compressed(cache, **data)
    return data

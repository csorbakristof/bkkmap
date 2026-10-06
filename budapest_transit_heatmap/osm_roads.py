"""Car road graph from an OpenStreetMap .osm.pbf extract.

The whole extract is parsed once into compact arrays (cached as .npz); each run then
cuts out its bounding box and turns lengths/speeds into travel times.
"""
import logging
import re
from array import array
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

import numpy as np

from config import CAR_BBOX_BUFFER_M, MAXSPEED_ZONES, NO_ACCESS_CLASSES, ROAD_CLASSES, TRAFFIC_SIGNAL_PENALTY_S
from geo import haversine_m
from osm_pbf import Block, dense_tagged, fields, iter_blocks, packed_list, zigzag_list

log = logging.getLogger(__name__)

ROADS_CACHE_VERSION = 1
CLASS_NAMES = list(ROAD_CLASSES)
_CLASS_ID = {c.encode(): i for i, c in enumerate(CLASS_NAMES)}
_NO_ACCESS = {b"no", b"private"}
_ALLOWED = {b"yes", b"designated", b"destination", b"permissive"}
_ONEWAY_FWD = {b"yes", b"true", b"1"}
_ONEWAY_BWD = {b"-1", b"reverse"}
_ONEWAY_SKIP = {b"reversible", b"alternating"}
_NUMBER = re.compile(rb"\d+(?:\.\d+)?")


@dataclass
class RoadGraph:
    node_lat: np.ndarray
    node_lon: np.ndarray
    node_signal: np.ndarray  # bool: highway=traffic_signals
    edge_src: np.ndarray  # directed edges, node indices
    edge_dst: np.ndarray
    edge_len_m: np.ndarray
    edge_speed_kmh: np.ndarray  # speed limit (tagged or class default)
    edge_class: np.ndarray  # index into CLASS_NAMES


def parse_maxspeed(value, default):
    """Speed limit in km/h from an OSM maxspeed value; `default` when unusable."""
    if not value:
        return default
    v = value.strip()
    if v.decode(errors="replace") in MAXSPEED_ZONES:
        return MAXSPEED_ZONES[v.decode()]
    nums = [float(m) for m in _NUMBER.findall(v)]
    if not nums:  # "none", "signals", "variable", ...
        return default
    speed = min(nums)  # "50;30" -> conservative
    if b"mph" in v:
        speed *= 1.609
    return speed if speed > 0 else default


def _car_way(tags):
    """(class_id, speed_kmh, oneway) for a car-usable way, or None."""
    cid = _CLASS_ID.get(tags.get(b"highway"))
    if cid is None or tags.get(b"area") == b"yes":
        return None
    car_ok = next((tags[k] for k in (b"motorcar", b"motor_vehicle", b"vehicle") if k in tags), None)
    if car_ok is not None:
        if car_ok not in _ALLOWED:
            return None
    elif tags.get(b"access") in _NO_ACCESS:
        return None
    ow = tags.get(b"oneway")
    if ow in _ONEWAY_SKIP:
        return None
    if ow in _ONEWAY_FWD:
        oneway = 1
    elif ow in _ONEWAY_BWD:
        oneway = -1
    elif ow is None and (CLASS_NAMES[cid] == "motorway" or tags.get(b"junction") in (b"roundabout", b"circular")):
        oneway = 1
    else:
        oneway = 0
    speed = parse_maxspeed(tags.get(b"maxspeed"), ROAD_CLASSES[CLASS_NAMES[cid]][0])
    return cid, speed, oneway


def _parse_pbf(path):
    """Two passes over the extract: car ways first, then coordinates of their nodes."""
    refs, counts = array("q"), array("i")
    w_class, w_speed, w_oneway = array("b"), array("f"), array("b")
    for data in iter_blocks(path):
        block = Block(data)
        hw = block.string_index(b"highway")
        if hw is None:
            continue
        hw_key = bytes([hw]) if hw < 128 else None  # quick pre-filter on the packed keys bytes
        strings = block.strings
        for way in block.ways():
            keys = vals = refs_buf = None
            for fn, val in fields(way):
                if fn == 2:
                    keys = val
                elif fn == 3:
                    vals = val
                elif fn == 8:
                    refs_buf = val
            if keys is None or refs_buf is None or (hw_key is not None and hw_key not in keys):
                continue
            tags = {strings[k]: strings[v] for k, v in zip(packed_list(keys), packed_list(vals))}
            car = _car_way(tags)
            if car is None:
                continue
            way_refs = list(accumulate(zigzag_list(packed_list(refs_buf))))
            if len(way_refs) < 2:
                continue
            refs.extend(way_refs)
            counts.append(len(way_refs))
            w_class.append(car[0])
            w_speed.append(car[1])
            w_oneway.append(car[2])
    refs = np.frombuffer(refs, np.int64)
    counts = np.frombuffer(counts, np.int32)
    log.info("OSM roads: %d car ways, %d node refs", len(counts), len(refs))

    node_ids, ref_node = np.unique(refs, return_inverse=True)
    lat = np.full(len(node_ids), np.nan)
    lon = np.full(len(node_ids), np.nan)
    signal = np.zeros(len(node_ids), bool)
    for data in iter_blocks(path):
        block = Block(data)
        ts = (block.string_index(b"highway"), block.string_index(b"traffic_signals"))
        for ids, nlat, nlon, kv in block.dense_nodes():
            pos = np.clip(np.searchsorted(node_ids, ids), 0, len(node_ids) - 1)
            hit = node_ids[pos] == ids
            lat[pos[hit]] = nlat[hit]
            lon[pos[hit]] = nlon[hit]
            sig = dense_tagged(kv, len(ids), *ts)
            signal[pos[hit & sig]] = True

    way_of_ref = np.repeat(np.arange(len(counts)), counts)
    seg = np.flatnonzero(way_of_ref[:-1] == way_of_ref[1:])
    a, b, w = ref_node[seg], ref_node[seg + 1], way_of_ref[seg]
    ok = np.isfinite(lat[a]) & np.isfinite(lat[b])  # nodes missing from a clipped extract
    a, b, w = a[ok], b[ok], w[ok]
    length = haversine_m(lat[a], lon[a], lat[b], lon[b])
    oneway = np.frombuffer(w_oneway, np.int8)[w]
    fwd, bwd = oneway >= 0, oneway <= 0
    speed = np.frombuffer(w_speed, np.float32)[w]
    cls = np.frombuffer(w_class, np.int8)[w]
    return {
        "node_lat": lat, "node_lon": lon, "node_signal": signal,
        "edge_src": np.concatenate([a[fwd], b[bwd]]).astype(np.int32),
        "edge_dst": np.concatenate([b[fwd], a[bwd]]).astype(np.int32),
        "edge_len_m": np.concatenate([length[fwd], length[bwd]]).astype(np.float32),
        "edge_speed_kmh": np.concatenate([speed[fwd], speed[bwd]]),
        "edge_class": np.concatenate([cls[fwd], cls[bwd]]),
    }


def _bbox_mask(lat, lon, bbox, buffer_m):
    min_lat, min_lon, max_lat, max_lon = bbox
    dlat = buffer_m / 111_320.0
    dlon = dlat / np.cos(np.radians((min_lat + max_lat) / 2))
    return (lat >= min_lat - dlat) & (lat <= max_lat + dlat) & (lon >= min_lon - dlon) & (lon <= max_lon + dlon)


def load_road_graph(pbf_path, bbox, cache_dir, buffer_m=CAR_BBOX_BUFFER_M):
    """Car road graph restricted to bbox + buffer; the parsed extract is cached on disk."""
    pbf_path = Path(pbf_path)
    stamp = int(pbf_path.stat().st_mtime)
    cache = Path(cache_dir) / "parsed" / f"roads_{pbf_path.stem.split('.')[0]}_{stamp}_v{ROADS_CACHE_VERSION}.npz"
    if cache.exists():
        log.info("OSM roads: loading parsed graph from %s", cache.name)
        data = dict(np.load(cache, allow_pickle=False))
    else:
        log.info("OSM roads: parsing %s (one-off, takes a few minutes)", pbf_path.name)
        data = _parse_pbf(pbf_path)
        cache.parent.mkdir(parents=True, exist_ok=True)
        for old in cache.parent.glob(f"roads_{pbf_path.stem.split('.')[0]}_*.npz"):
            old.unlink()
        np.savez_compressed(cache, **data)

    keep_node = _bbox_mask(data["node_lat"], data["node_lon"], bbox, buffer_m)
    keep_edge = keep_node[data["edge_src"]] & keep_node[data["edge_dst"]]
    new_index = np.cumsum(keep_node) - 1
    g = RoadGraph(
        node_lat=data["node_lat"][keep_node], node_lon=data["node_lon"][keep_node],
        node_signal=data["node_signal"][keep_node],
        edge_src=new_index[data["edge_src"][keep_edge]].astype(np.int32),
        edge_dst=new_index[data["edge_dst"][keep_edge]].astype(np.int32),
        edge_len_m=data["edge_len_m"][keep_edge], edge_speed_kmh=data["edge_speed_kmh"][keep_edge],
        edge_class=data["edge_class"][keep_edge])
    log.info("OSM roads: %d nodes, %d directed edges within bbox+%.0f km",
             len(g.node_lat), len(g.edge_src), buffer_m / 1000)
    return g


def edge_minutes(g, traffic_factor):
    """Expected driving time per edge: length at the achieved share of the speed limit,
    plus a traffic-signal delay when the edge ends at a signalized node."""
    share = np.array([ROAD_CLASSES[c][1] for c in CLASS_NAMES])[g.edge_class]
    kmh = np.maximum(g.edge_speed_kmh * share * traffic_factor, 1.0)
    return g.edge_len_m / (kmh * 1000.0 / 60.0) + g.node_signal[g.edge_dst] * (TRAFFIC_SIGNAL_PENALTY_S / 60.0)


def access_nodes(g):
    """Nodes where a car trip can start or end: on at least one non-motorway-like road."""
    no_access = np.array([c in NO_ACCESS_CLASSES for c in CLASS_NAMES])[g.edge_class]
    ok = np.zeros(len(g.node_lat), bool)
    ok[g.edge_src[~no_access]] = True
    ok[g.edge_dst[~no_access]] = True
    return ok

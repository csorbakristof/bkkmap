"""Minimal pure-Python/numpy reader for OpenStreetMap .osm.pbf files.

Only what the road graph needs: ways (tags + node refs) and dense nodes (ids,
coordinates, keys_vals). See https://wiki.openstreetmap.org/wiki/PBF_Format.
"""
import struct
import zlib

import numpy as np


def _varint(buf, pos):
    b = buf[pos]
    if b < 128:
        return b, pos + 1
    result, shift = b & 0x7F, 7
    pos += 1
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if b < 128:
            return result, pos
        shift += 7


def fields(buf):
    """Yield (field_number, value) of a protobuf message; length-delimited values are bytes."""
    pos, n = 0, len(buf)
    while pos < n:
        key, pos = _varint(buf, pos)
        wt = key & 7
        if wt == 0:
            val, pos = _varint(buf, pos)
        elif wt == 2:
            ln, pos = _varint(buf, pos)
            val = buf[pos:pos + ln]
            pos += ln
        elif wt == 1:
            val = buf[pos:pos + 8]
            pos += 8
        elif wt == 5:
            val = buf[pos:pos + 4]
            pos += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wt}")
        yield key >> 3, val


def packed_list(buf):
    """Decode a short packed varint field in pure Python (faster than numpy for a few values)."""
    out, pos, n = [], 0, len(buf)
    while pos < n:
        v, pos = _varint(buf, pos)
        out.append(v)
    return out


def packed_array(buf):
    """Vectorized decode of a packed varint field to uint64."""
    b = np.frombuffer(buf, np.uint8)
    if not len(b):
        return np.zeros(0, np.uint64)
    ends = np.flatnonzero(b < 128)
    starts = np.empty_like(ends)
    starts[0] = 0
    starts[1:] = ends[:-1] + 1
    grp = np.repeat(np.arange(len(ends)), ends - starts + 1)
    shift = ((np.arange(len(b)) - starts[grp]) * 7).astype(np.uint64)
    return np.add.reduceat((b & 0x7F).astype(np.uint64) << shift, starts)


def zigzag(v):
    """Signed (sint64) values from zigzag-encoded uint64."""
    v = np.asarray(v, np.uint64)
    return (v >> np.uint64(1)).astype(np.int64) ^ -(v & np.uint64(1)).astype(np.int64)


def zigzag_list(values):
    return [(v >> 1) ^ -(v & 1) for v in values]


def iter_blocks(path):
    """Yield the decompressed bytes of every OSMData blob (a PrimitiveBlock)."""
    with open(path, "rb") as f:
        while True:
            head = f.read(4)
            if len(head) < 4:
                return
            header = f.read(struct.unpack(">I", head)[0])
            btype, size = None, 0
            for fn, val in fields(header):
                if fn == 1:
                    btype = bytes(val).decode()
                elif fn == 3:
                    size = val
            blob = f.read(size)
            if btype != "OSMData":
                continue
            raw = zdata = None
            for fn, val in fields(blob):
                if fn == 1:
                    raw = val
                elif fn == 3:
                    zdata = val
            if raw is not None:
                yield raw
            elif zdata is not None:
                yield zlib.decompress(zdata)
            else:
                raise ValueError("Unsupported PBF blob compression (only raw/zlib)")


def is_pbf(path):
    """Cheap sanity check: the first blob header must announce an OSMHeader."""
    with open(path, "rb") as f:
        head = f.read(4)
        if len(head) < 4:
            return False
        return b"OSMHeader" in f.read(min(struct.unpack(">I", head)[0], 64))


class Block:
    """A parsed PrimitiveBlock: string table, coordinate scaling and raw primitive groups."""

    def __init__(self, data):
        self.strings, self.groups = [], []
        self.granularity, self.lat_offset, self.lon_offset = 100, 0, 0
        for fn, val in fields(data):
            if fn == 1:
                self.strings = [bytes(s) for f2, s in fields(val) if f2 == 1]
            elif fn == 2:
                self.groups.append(val)
            elif fn == 17:
                self.granularity = val
            elif fn == 19:
                self.lat_offset = _int64(val)
            elif fn == 20:
                self.lon_offset = _int64(val)

    def string_index(self, s):
        try:
            return self.strings.index(s)
        except ValueError:
            return None

    def ways(self):
        """Yield the raw bytes of every Way message."""
        yield from self._members(3)

    def relations(self):
        """Yield the raw bytes of every Relation message."""
        yield from self._members(4)

    def _members(self, field):
        for g in self.groups:
            for fn, val in fields(g):
                if fn == field:
                    yield val

    def dense_nodes(self):
        """Yield (ids int64, lat float64, lon float64, keys_vals uint64) per DenseNodes group."""
        for g in self.groups:
            for fn, val in fields(g):
                if fn != 2:
                    continue
                ids = lat = lon = None
                kv = np.zeros(0, np.uint64)
                for f2, v2 in fields(val):
                    if f2 == 1:
                        ids = np.cumsum(zigzag(packed_array(v2)))
                    elif f2 == 8:
                        lat = np.cumsum(zigzag(packed_array(v2)))
                    elif f2 == 9:
                        lon = np.cumsum(zigzag(packed_array(v2)))
                    elif f2 == 10:
                        kv = packed_array(v2)
                if ids is None:
                    continue
                yield (ids,
                       1e-9 * (self.lat_offset + self.granularity * lat),
                       1e-9 * (self.lon_offset + self.granularity * lon),
                       kv)


def _int64(v):
    """Plain (non-zigzag) int64 varint value as Python int."""
    return v - (1 << 64) if v >= 1 << 63 else v


def _dense_layout(kv):
    """(node index of every keys_vals position, segment starts, is-key mask) of a DenseNodes keys_vals array.

    keys_vals is, per node, k1 v1 k2 v2 ... 0 (string-table indices).
    """
    zero = kv == 0
    node_of = np.cumsum(zero) - zero
    seg_start = np.flatnonzero(np.r_[True, zero[:-1]])
    is_key = ((np.arange(len(kv)) - seg_start[node_of]) % 2 == 0) & ~zero
    return node_of, seg_start, is_key


def dense_tagged(kv, n_nodes, key_idx, val_idx):
    """Boolean mask of dense nodes carrying tag key=val."""
    mask = np.zeros(n_nodes, bool)
    if not len(kv) or key_idx is None or val_idx is None:
        return mask
    node_of, _, is_key = _dense_layout(kv)
    hit = np.flatnonzero(is_key[:-1] & (kv[:-1] == key_idx) & (kv[1:] == val_idx))
    mask[node_of[hit]] = True
    return mask


def dense_with_key(kv, key_idx, strings):
    """{node index: tags dict} for the dense nodes that carry key `key_idx`."""
    if not len(kv) or key_idx is None:
        return {}
    node_of, seg_start, is_key = _dense_layout(kv)
    out = {}
    for node in np.unique(node_of[np.flatnonzero(is_key & (kv == key_idx))]):
        a = seg_start[node]
        b = seg_start[node + 1] - 1 if node + 1 < len(seg_start) else len(kv) - 1
        seg = kv[a:b].tolist()
        out[int(node)] = {strings[k]: strings[v] for k, v in zip(seg[::2], seg[1::2])}
    return out

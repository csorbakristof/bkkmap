"""Active service resolution, spatial stop filtering and connection extraction."""
import io
import logging
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from config import BBOX_BUFFER_M
from geo import haversine_m

log = logging.getLogger(__name__)

PARSED_CACHE_VERSION = 1
STOP_TIMES_CHUNK_ROWS = 1_000_000


def _read_csv(zf: zipfile.ZipFile, name: str, **kwargs) -> pd.DataFrame | None:
    if name not in zf.namelist():
        return None
    with zf.open(name) as f:
        return pd.read_csv(io.TextIOWrapper(f, encoding="utf-8-sig"), dtype=str, **kwargs)


def active_service_ids(zf: zipfile.ZipFile, day: date) -> set[str]:
    """service_ids running on `day` according to calendar.txt and calendar_dates.txt."""
    ymd = day.strftime("%Y%m%d")
    active: set[str] = set()

    cal = _read_csv(zf, "calendar.txt")
    if cal is not None and len(cal):
        weekday_col = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][day.weekday()]
        mask = (cal["start_date"] <= ymd) & (cal["end_date"] >= ymd) & (cal[weekday_col] == "1")
        active.update(cal.loc[mask, "service_id"])

    cd = _read_csv(zf, "calendar_dates.txt")
    if cd is not None and len(cd):
        cd = cd[cd["date"] == ymd]
        active.update(cd.loc[cd["exception_type"] == "1", "service_id"])
        active.difference_update(cd.loc[cd["exception_type"] == "2", "service_id"])
    return active


def _gtfs_time_to_sec(s: pd.Series) -> np.ndarray:
    """'HH:MM:SS' (hours may exceed 24) -> seconds after midnight of the service day."""
    parts = s.str.strip().str.split(":", expand=True).astype(np.int32)
    return (parts[0] * 3600 + parts[1] * 60 + parts[2]).to_numpy(np.int32)


def _feed_connections(zf: zipfile.ZipFile, day: date) -> dict[str, np.ndarray]:
    """Elementary connections of one feed valid on `day`.

    Includes trips of the previous service day that run past midnight (GTFS times
    > 24:00:00), shifted by -24h so all times are relative to `day` midnight.
    """
    trips = _read_csv(zf, "trips.txt", usecols=["trip_id", "service_id"])
    day_trips = []
    for offset, d in ((0, day), (-86400, day - timedelta(days=1))):
        services = active_service_ids(zf, d)
        t = trips.loc[trips["service_id"].isin(services), ["trip_id"]].copy()
        t["offset"] = offset
        day_trips.append(t)
    day_trips = pd.concat(day_trips, ignore_index=True)
    day_trips["trip_idx"] = np.arange(len(day_trips), dtype=np.int32)
    wanted = set(day_trips["trip_id"])
    log.info("  %d active trips (%d today, %d from previous day)", len(day_trips),
             (day_trips["offset"] == 0).sum(), (day_trips["offset"] != 0).sum())

    cols = ["trip_id", "stop_id", "arrival_time", "departure_time", "stop_sequence"]
    chunks = []
    with zf.open("stop_times.txt") as f:
        reader = pd.read_csv(io.TextIOWrapper(f, encoding="utf-8-sig"), dtype=str, usecols=cols,
                             chunksize=STOP_TIMES_CHUNK_ROWS)
        for chunk in reader:
            chunk = chunk[chunk["trip_id"].isin(wanted)]
            # Times may be blank for non-timepoints; GTFS requires them at least at ends.
            chunk = chunk.dropna(subset=["arrival_time", "departure_time"])
            chunks.append(chunk)
    st = pd.concat(chunks, ignore_index=True)
    st["stop_sequence"] = st["stop_sequence"].astype(np.int32)
    st["arr"] = _gtfs_time_to_sec(st["arrival_time"])
    st["dep"] = _gtfs_time_to_sec(st["departure_time"])
    st = st.drop(columns=["arrival_time", "departure_time"])

    # A trip active on both days appears twice, once per offset.
    st = st.merge(day_trips, on="trip_id", how="inner")
    st = st.sort_values(["trip_idx", "stop_sequence"], kind="stable").reset_index(drop=True)

    trip = st["trip_idx"].to_numpy()
    same_trip = trip[:-1] == trip[1:]
    i = np.flatnonzero(same_trip)
    offset = st["offset"].to_numpy(np.int32)
    t_dep = st["dep"].to_numpy(np.int32)[i] + offset[i]
    t_arr = st["arr"].to_numpy(np.int32)[i + 1] + offset[i]
    stop = st["stop_id"].to_numpy()
    keep = t_dep >= 0
    return {
        "s_dep": stop[i][keep].astype(str),
        "s_arr": stop[i + 1][keep].astype(str),
        "t_dep": t_dep[keep],
        "t_arr": t_arr[keep],
        "trip": trip[i][keep].astype(np.int32),
    }


def _load_feed(name: str, zf: zipfile.ZipFile, day: date, cache_dir: Path):
    """Stops and connections for one feed, cached on disk per (feed version, date)."""
    src = Path(zf.filename)
    stamp = int(src.stat().st_mtime)
    cache = cache_dir / "parsed" / f"{name}_{day:%Y%m%d}_{stamp}_v{PARSED_CACHE_VERSION}.npz"
    if cache.exists():
        log.info("Feed %s: loading parsed connections from %s", name, cache.name)
        data = dict(np.load(cache, allow_pickle=False))
    else:
        log.info("Feed %s: parsing timetable for %s", name, day)
        stops = _read_csv(zf, "stops.txt", usecols=lambda c: c in {"stop_id", "stop_name", "stop_lat", "stop_lon"})
        stops = stops.dropna(subset=["stop_lat", "stop_lon"])
        data = _feed_connections(zf, day)
        data.update(stop_id=stops["stop_id"].to_numpy(str),
                    stop_name=stops["stop_name"].fillna("").to_numpy(str),
                    stop_lat=stops["stop_lat"].astype(float).to_numpy(),
                    stop_lon=stops["stop_lon"].astype(float).to_numpy())
        cache.parent.mkdir(parents=True, exist_ok=True)
        for old in cache.parent.glob(f"{name}_{day:%Y%m%d}_*.npz"):
            old.unlink()
        np.savez_compressed(cache, **data)
    log.info("Feed %s: %d stops, %d connections", name, len(data["stop_id"]), len(data["t_dep"]))
    return data


def _in_buffered_bbox(lat, lon, bbox, buffer_m):
    min_lat, min_lon, max_lat, max_lon = bbox
    clat = np.clip(lat, min_lat, max_lat)
    clon = np.clip(lon, min_lon, max_lon)
    return haversine_m(lat, lon, clat, clon) <= buffer_m


def build_timetable(feeds: dict[str, zipfile.ZipFile], day: date, bbox, cache_dir, buffer_m=BBOX_BUFFER_M):
    """Merge all feeds into one stop table and a chronologically sorted connection table.

    Returns (stops_df, connections_df). stops_df is indexed 0..n-1 and has columns
    stop_id, stop_name, lat, lon. connections_df has integer stop indices in
    s_dep/s_arr, seconds after `day` midnight in t_dep/t_arr and a global trip_id.
    """
    cache_dir = Path(cache_dir)
    stop_frames, conn_frames = [], []
    trip_offset = 0
    for name, zf in feeds.items():
        try:
            d = _load_feed(name, zf, day, cache_dir)
        except Exception as exc:  # noqa: BLE001 - one broken optional feed should not kill the run
            log.warning("Feed %s: could not be parsed (%s); skipping", name, exc)
            continue
        stop_frames.append(pd.DataFrame({
            "stop_id": np.char.add(f"{name}:", d["stop_id"]),
            "stop_name": d["stop_name"], "lat": d["stop_lat"], "lon": d["stop_lon"]}))
        conn_frames.append(pd.DataFrame({
            "s_dep": np.char.add(f"{name}:", d["s_dep"]), "s_arr": np.char.add(f"{name}:", d["s_arr"]),
            "t_dep": d["t_dep"], "t_arr": d["t_arr"], "trip_id": d["trip"] + trip_offset}))
        if len(d["trip"]):
            trip_offset += int(d["trip"].max()) + 1

    if not conn_frames:
        raise RuntimeError("No usable GTFS feed")

    stops = pd.concat(stop_frames, ignore_index=True).drop_duplicates("stop_id")
    stops = stops[_in_buffered_bbox(stops["lat"].to_numpy(), stops["lon"].to_numpy(), bbox, buffer_m)]
    stops = stops.reset_index(drop=True)
    index = pd.Series(np.arange(len(stops), dtype=np.int32), index=stops["stop_id"])

    conns = pd.concat(conn_frames, ignore_index=True)
    conns["s_dep"] = conns["s_dep"].map(index)
    conns["s_arr"] = conns["s_arr"].map(index)
    conns = conns.dropna(subset=["s_dep", "s_arr"])
    conns = conns.astype({"s_dep": np.int32, "s_arr": np.int32})
    conns = conns.sort_values(["t_dep", "t_arr"], kind="stable").reset_index(drop=True)
    log.info("Timetable: %d stops within bbox+%.0f km, %d connections", len(stops), buffer_m / 1000, len(conns))
    return stops, conns

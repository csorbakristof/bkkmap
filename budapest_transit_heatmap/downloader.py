"""HTTP fetcher & cache manager for GTFS feeds."""
import logging
import os
import time
import zipfile
from pathlib import Path

import requests

from config import FEED_MAX_AGE_DAYS, GTFS_FEEDS, HTTP_USER_AGENT

log = logging.getLogger(__name__)


def _is_fresh(path: Path, max_age_days: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(".part")
    with requests.get(url, headers={"User-Agent": HTTP_USER_AGENT}, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    # Validate before replacing a possibly good cached copy.
    with zipfile.ZipFile(tmp) as zf:
        if "stop_times.txt" not in zf.namelist():
            raise ValueError(f"{url} is not a GTFS archive (no stop_times.txt)")
    os.replace(tmp, dest)


def _fetch(name: str, url: str, cache_dir: Path, max_age_days: float) -> Path | None:
    dest = cache_dir / f"{name}.zip"
    if _is_fresh(dest, max_age_days):
        log.info("Feed %s: using cached %s", name, dest)
        return dest
    try:
        log.info("Feed %s: downloading %s", name, url)
        _download(url, dest)
        log.info("Feed %s: saved %.1f MB", name, dest.stat().st_size / 1e6)
        return dest
    except Exception as exc:  # noqa: BLE001 - network errors of all kinds
        if dest.exists():
            log.warning("Feed %s: download failed (%s); using stale cached copy", name, exc)
            return dest
        log.warning("Feed %s: download failed (%s)", name, exc)
        return None


def download_gtfs_feeds(cache_dir, max_age_days=FEED_MAX_AGE_DAYS, extra_feeds=()):
    """Ensure all feeds are present in cache_dir and return {name: zipfile.ZipFile}.

    extra_feeds: iterable of URLs or local .zip paths. Any other *.zip already present
    in cache_dir (e.g. a manually obtained mav.zip) is used as well.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    for name, feed in GTFS_FEEDS.items():
        path = _fetch(name, feed["url"], cache_dir, max_age_days)
        if path is None and feed["required"]:
            raise RuntimeError(f"Required GTFS feed '{name}' could not be downloaded")
        if path is not None:
            paths[name] = path

    for i, src in enumerate(extra_feeds):
        if src.startswith(("http://", "https://")):
            path = _fetch(f"extra{i}", src, cache_dir, max_age_days)
            if path is None:
                raise RuntimeError(f"Extra GTFS feed could not be downloaded: {src}")
            paths[f"extra{i}"] = path
        else:
            path = Path(src)
            if not path.exists():
                raise FileNotFoundError(src)
            paths[path.stem] = path

    for path in sorted(cache_dir.glob("*.zip")):
        if path.stem not in paths and path not in paths.values():
            log.info("Feed %s: found manually placed archive %s", path.stem, path)
            paths[path.stem] = path

    return {name: zipfile.ZipFile(path) for name, path in paths.items()}

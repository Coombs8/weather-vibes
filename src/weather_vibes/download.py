from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ACCESS_URL, README_URL, STATIONS_URL, Paths
from .stations import Station, parse_stations

LOG = logging.getLogger(__name__)


@dataclass
class ManifestEntry:
    source_url: str
    local_path: str
    status: str
    retrieved_at: str
    size_bytes: int | None = None
    sha256: str | None = None
    error: str | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_file(url: str, target: Path, retries: int = 3) -> ManifestEntry:
    """Download atomically, resuming a partial file when the server supports Range."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    now = datetime.now(timezone.utc).isoformat()
    for attempt in range(retries):
        try:
            headers: dict[str, str] = {"User-Agent": "weather-vibes/0.1"}
            mode = "wb"
            offset = partial.stat().st_size if partial.exists() else 0
            if offset:
                headers["Range"] = f"bytes={offset}-"
                mode = "ab"
            if target.exists():
                request = Request(url, headers={**headers, "If-Modified-Since": datetime.fromtimestamp(
                    target.stat().st_mtime, timezone.utc
                ).strftime("%a, %d %b %Y %H:%M:%S GMT")})
            else:
                request = Request(url, headers=headers)
            try:
                response = urlopen(request, timeout=60)
            except HTTPError as exc:
                if exc.code == 304:
                    return ManifestEntry(url, str(target), "skipped_unchanged", now,
                                         target.stat().st_size, sha256(target))
                raise
            if offset and response.status != 206:
                mode, offset = "wb", 0
            with response, partial.open(mode) as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            partial.replace(target)
            return ManifestEntry(url, str(target), "success", now, target.stat().st_size, sha256(target))
        except (OSError, HTTPError, URLError) as exc:
            if attempt + 1 == retries:
                return ManifestEntry(url, str(target), "failed", now, error=str(exc))
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def append_manifest(path: Path, entries: list[ManifestEntry]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for entry in entries:
            output.write(json.dumps(asdict(entry), sort_keys=True) + "\n")


def fetch_metadata(paths: Paths) -> list[ManifestEntry]:
    paths.create()
    entries = [
        download_file(STATIONS_URL, paths.raw / "ghcnd-stations.txt"),
        download_file(README_URL, paths.raw / "noaa-readme.txt"),
    ]
    append_manifest(paths.manifest, entries)
    failures = [item for item in entries if item.status == "failed"]
    if failures:
        raise RuntimeError("metadata download failed: " + "; ".join(item.error or "" for item in failures))
    return entries


def fetch_stations(paths: Paths, stations: list[Station], workers: int = 6) -> list[ManifestEntry]:
    def fetch(station: Station) -> ManifestEntry:
        return download_file(
            f"{ACCESS_URL}/{station.station_id}.csv",
            paths.station_files / f"{station.station_id}.csv",
        )

    entries: list[ManifestEntry] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch, station): station.station_id for station in stations}
        for future in as_completed(futures):
            entry = future.result()
            entries.append(entry)
            LOG.info("%s: %s", futures[future], entry.status)
    append_manifest(paths.manifest, entries)
    return entries


def download(paths: Paths, limit: int | None = None, workers: int = 6) -> list[ManifestEntry]:
    fetch_metadata(paths)
    stations = parse_stations(paths.raw / "ghcnd-stations.txt")
    if limit is not None:
        stations = stations[:limit]
    entries = fetch_stations(paths, stations, workers)
    failures = sum(entry.status == "failed" for entry in entries)
    if failures:
        LOG.warning("%d of %d station downloads failed; successful files remain usable", failures, len(entries))
    return entries


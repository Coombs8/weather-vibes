from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily"
STATIONS_URL = f"{ROOT_URL}/doc/ghcnd-stations.txt"
README_URL = f"{ROOT_URL}/doc/readme.txt"
ACCESS_URL = f"{ROOT_URL}/access"
CORE_ELEMENTS = ("TMAX", "TMIN", "TAVG", "PRCP", "SNOW", "SNWD")


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def station_files(self) -> Path:
        return self.raw / "stations"

    @property
    def conformed(self) -> Path:
        return self.root / "conformed"

    @property
    def database(self) -> Path:
        return self.root / "weather.duckdb"

    @property
    def manifest(self) -> Path:
        return self.raw / "manifest.jsonl"

    def create(self) -> None:
        for directory in (self.raw, self.station_files, self.conformed):
            directory.mkdir(parents=True, exist_ok=True)


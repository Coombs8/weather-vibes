from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Station:
    station_id: str
    latitude: float
    longitude: float
    elevation_m: float | None
    state: str
    station_name: str
    gsn_flag: str | None
    hcn_crn_flag: str | None
    wmo_id: str | None


def _optional(value: str) -> str | None:
    value = value.strip()
    return value or None


def parse_station_line(line: str) -> Station:
    """Parse NOAA ghcnd-stations.txt fixed-width layout (README section IV)."""
    line = line.rstrip("\r\n").ljust(85)
    if not line[0:11].strip() or not line[12:20].strip() or not line[21:30].strip():
        raise ValueError("station metadata line lacks required ID or coordinates")
    elevation = line[21:30].strip()
    return Station(
        station_id=line[0:11].strip(),
        latitude=float(line[12:20]),
        longitude=float(line[21:30]),
        elevation_m=float(line[31:37]) if line[31:37].strip() != "-999.9" else None,
        state=line[38:40].strip(),
        station_name=line[41:71].strip(),
        gsn_flag=_optional(line[72:75]),
        hcn_crn_flag=_optional(line[76:79]),
        wmo_id=_optional(line[80:85]),
    )


def parse_stations(path: Path, state: str = "MI") -> list[Station]:
    stations: list[Station] = []
    # NOAA describes this as ASCII, but current metadata contains UTF-8
    # characters in a small number of station names.
    with path.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            try:
                station = parse_station_line(line)
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            if station.state == state:
                stations.append(station)
    return stations

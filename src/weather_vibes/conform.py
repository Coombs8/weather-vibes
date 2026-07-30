from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .config import CORE_ELEMENTS, Paths
from .stations import Station, parse_stations

LOG = logging.getLogger(__name__)


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def station_values(stations: list[Station]) -> str:
    def val(value: object | None) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, str):
            return sql_string(value)
        return str(value)

    return ",\n".join(
        "(" + ",".join(val(value) for value in (
            s.station_id, s.station_name, s.state, s.latitude, s.longitude, s.elevation_m,
            s.gsn_flag, s.hcn_crn_flag, s.wmo_id
        )) + ")" for s in stations
    )


def _available_files(paths: Paths, station_ids: set[str] | None = None) -> list[Path]:
    files = sorted(paths.station_files.glob("*.csv"))
    if station_ids is not None:
        files = [path for path in files if path.stem in station_ids]
    if not files:
        raise RuntimeError(f"no station CSV files found under {paths.station_files}; run download first")
    return files


def _headers(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as source:
        return set(next(csv.reader(source)))


def build_conformed(paths: Paths) -> None:
    paths.create()
    stations = parse_stations(paths.raw / "ghcnd-stations.txt")
    station_by_id = {station.station_id: station for station in stations}
    files = _available_files(paths, set(station_by_id))
    present_ids = {path.stem for path in files}
    selected = [station_by_id[station_id] for station_id in sorted(present_ids)]
    first_header = _headers(files[0])
    required = {"STATION", "DATE"}
    if not required <= first_header:
        raise ValueError(f"{files[0]} lacks required columns {required - first_header}")

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET TimeZone='UTC'")
    file_list = "[" + ",".join(sql_string(str(path)) for path in files) + "]"
    stations_out = sql_string(str(paths.conformed / "stations.parquet"))
    daily_out = sql_string(str(paths.conformed / "daily_weather.parquet"))

    con.execute(f"""
        CREATE TEMP TABLE station_metadata(
          station_id VARCHAR, station_name VARCHAR, state VARCHAR, latitude DOUBLE,
          longitude DOUBLE, elevation_m DOUBLE, gsn_flag VARCHAR, hcn_crn_flag VARCHAR,
          wmo_id VARCHAR
        );
        INSERT INTO station_metadata VALUES {station_values(selected)};
    """)
    columns = {row[0] for row in con.execute(
        f"DESCRIBE SELECT * FROM read_csv({file_list}, union_by_name=true, all_varchar=true)"
    ).fetchall()}

    expressions: list[str] = []
    flags: list[str] = []
    for element in CORE_ELEMENTS:
        value = f'TRY_CAST("{element}" AS DOUBLE)' if element in columns else "NULL"
        attrs = f'COALESCE("{element}_ATTRIBUTES", \'\')' if f"{element}_ATTRIBUTES" in columns else "''"
        scale = "10.0" if element in {"TMAX", "TMIN", "TAVG", "PRCP"} else "1.0"
        name = {"TMAX": "tmax_c", "TMIN": "tmin_c", "TAVG": "reported_tavg_c",
                "PRCP": "prcp_mm", "SNOW": "snow_mm", "SNWD": "snow_depth_mm"}[element]
        expressions.append(f"{value} / {scale} AS {name}")
        lower = element.lower()
        flags.extend([
            f"NULLIF(split_part({attrs}, ',', 1), '') AS {lower}_measurement_flag",
            f"NULLIF(split_part({attrs}, ',', 2), '') AS {lower}_quality_flag",
            f"NULLIF(split_part({attrs}, ',', 3), '') AS {lower}_source_flag",
            f"NULLIF(split_part({attrs}, ',', 4), '') AS {lower}_observation_time",
            f"split_part({attrs}, ',', 1) = 'T' AS {lower}_is_trace",
        ])

    timestamp = datetime.now(timezone.utc).isoformat()
    con.execute(f"""
      CREATE TEMP VIEW raw_daily AS
      SELECT *, filename FROM read_csv({file_list}, union_by_name=true, all_varchar=true,
                                       filename=true, ignore_errors=false);
      CREATE TEMP TABLE daily_stage AS
      SELECT
        STATION AS station_id, TRY_CAST(DATE AS DATE) AS observation_date,
        year(TRY_CAST(DATE AS DATE))::SMALLINT AS year,
        month(TRY_CAST(DATE AS DATE))::TINYINT AS month,
        day(TRY_CAST(DATE AS DATE))::TINYINT AS day,
        dayofyear(TRY_CAST(DATE AS DATE))::SMALLINT AS day_of_year,
        {", ".join(expressions)},
        {", ".join(flags)},
        {sql_string(timestamp)}::TIMESTAMP AS ingestion_timestamp
      FROM raw_daily;
      CREATE TEMP TABLE daily_final AS
      SELECT *,
        CASE WHEN tmax_quality_flag IS NULL THEN tmax_c END AS usable_tmax_c,
        CASE WHEN tmin_quality_flag IS NULL THEN tmin_c END AS usable_tmin_c,
        CASE WHEN tavg_quality_flag IS NULL THEN reported_tavg_c END AS usable_reported_tavg_c,
        CASE WHEN tmax_quality_flag IS NULL AND tmin_quality_flag IS NULL
                  AND tmax_c IS NOT NULL AND tmin_c IS NOT NULL
             THEN (tmax_c + tmin_c) / 2 END AS calculated_tavg_c,
        COALESCE(CASE WHEN tavg_quality_flag IS NULL THEN reported_tavg_c END,
                 CASE WHEN tmax_quality_flag IS NULL AND tmin_quality_flag IS NULL
                            AND tmax_c IS NOT NULL AND tmin_c IS NOT NULL
                      THEN (tmax_c + tmin_c) / 2 END) AS best_available_tavg_c,
        coalesce(tmax_quality_flag, tmin_quality_flag, tavg_quality_flag,
                 prcp_quality_flag, snow_quality_flag, snwd_quality_flag) IS NOT NULL
          AS is_quality_flagged,
        (tmax_quality_flag IS NULL AND tmin_quality_flag IS NULL
          AND (tmax_c IS NOT NULL OR tmin_c IS NOT NULL OR reported_tavg_c IS NOT NULL))
          AS is_temperature_usable,
        (prcp_quality_flag IS NULL AND prcp_mm IS NOT NULL) AS is_precipitation_usable,
        (snow_quality_flag IS NULL AND snow_mm IS NOT NULL) AS is_snow_usable
      FROM daily_stage;
      COPY (
        SELECT m.*, min(d.observation_date) AS first_observation_date,
                    max(d.observation_date) AS last_observation_date
        FROM station_metadata m LEFT JOIN daily_final d USING (station_id)
        GROUP BY ALL ORDER BY station_id
      ) TO {stations_out} (FORMAT PARQUET, COMPRESSION ZSTD);
      COPY (SELECT * FROM daily_final ORDER BY station_id, observation_date)
        TO {daily_out}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000);
    """)
    con.close()
    LOG.info("built conformed data for %d stations from %d files", len(selected), len(files))

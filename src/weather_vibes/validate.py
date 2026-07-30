from __future__ import annotations

import duckdb

from .config import Paths
from .conform import sql_string


CHECKS: dict[str, str] = {
    "valid_dates": "SELECT count(*) FROM daily WHERE observation_date IS NULL",
    "unique_grain": """SELECT count(*) FROM (
        SELECT station_id, observation_date FROM daily GROUP BY ALL HAVING count(*) > 1)""",
    "no_orphan_stations": """SELECT count(*) FROM daily d
        ANTI JOIN stations s USING (station_id)""",
    "michigan_only": "SELECT count(*) FROM stations WHERE state <> 'MI'",
    "coordinate_bounds": """SELECT count(*) FROM stations
        WHERE latitude NOT BETWEEN -90 AND 90 OR longitude NOT BETWEEN -180 AND 180""",
    "temperature_order": """SELECT count(*) FROM daily
        WHERE usable_tmin_c IS NOT NULL AND usable_tmax_c IS NOT NULL
          AND usable_tmin_c > usable_tmax_c""",
    "nonnegative_hydrology": """SELECT count(*) FROM daily WHERE
        (is_precipitation_usable AND prcp_mm < 0)
        OR (is_snow_usable AND snow_mm < 0)
        OR (snwd_quality_flag IS NULL AND snow_depth_mm < 0)""",
}


def validate(paths: Paths) -> dict[str, int]:
    con = duckdb.connect()
    con.execute(f"""
      CREATE VIEW daily AS SELECT * FROM read_parquet(
        {sql_string(str(paths.conformed / "daily_weather.parquet"))});
      CREATE VIEW stations AS SELECT * FROM read_parquet(
        {sql_string(str(paths.conformed / "stations.parquet"))});
    """)
    results = {name: con.execute(query).fetchone()[0] for name, query in CHECKS.items()}
    con.close()
    failures = {name: count for name, count in results.items() if count}
    if failures:
        raise RuntimeError("validation failed: " + ", ".join(f"{name}={count}" for name, count in failures.items()))
    return results


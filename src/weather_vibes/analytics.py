from __future__ import annotations

import logging

import duckdb

from .config import Paths
from .conform import sql_string

LOG = logging.getLogger(__name__)


def build_analytics(paths: Paths) -> None:
    stations = paths.conformed / "stations.parquet"
    daily = paths.conformed / "daily_weather.parquet"
    if not stations.exists() or not daily.exists():
        raise RuntimeError("conformed Parquet is missing; run build-conformed first")
    con = duckdb.connect(str(paths.database))
    con.execute("SET TimeZone='UTC'")
    con.execute(f"""
    CREATE OR REPLACE VIEW stations AS SELECT * FROM read_parquet({sql_string(str(stations))});
    CREATE OR REPLACE VIEW daily_weather AS SELECT * FROM read_parquet({sql_string(str(daily))});

    CREATE OR REPLACE VIEW daily_metrics AS
    SELECT *,
      greatest(0, 18.3333333333 - best_available_tavg_c) AS heating_degree_days_65f,
      greatest(0, best_available_tavg_c - 18.3333333333) AS cooling_degree_days_65f,
      greatest(0, best_available_tavg_c - 10.0) AS growing_degree_days_50f
    FROM daily_weather;

    CREATE OR REPLACE VIEW station_monthly_summary AS
    SELECT station_id, year, month,
      avg(usable_tmax_c) AS mean_tmax_c,
      avg(usable_tmin_c) AS mean_tmin_c,
      avg(best_available_tavg_c) AS mean_tavg_c,
      sum(prcp_mm) FILTER (WHERE is_precipitation_usable) AS total_prcp_mm,
      sum(snow_mm) FILTER (WHERE is_snow_usable) AS total_snow_mm,
      max(snow_depth_mm) FILTER (WHERE snwd_quality_flag IS NULL) AS max_snow_depth_mm,
      sum(heating_degree_days_65f) AS heating_degree_days_65f,
      sum(cooling_degree_days_65f) AS cooling_degree_days_65f,
      sum(growing_degree_days_50f) AS growing_degree_days_50f,
      count(*) FILTER (WHERE usable_tmin_c <= 0) AS days_at_or_below_freezing,
      count(*) FILTER (WHERE usable_tmin_c < -17.7777777778) AS days_below_0f,
      count(*) FILTER (WHERE usable_tmax_c >= 32.2222222222) AS days_at_or_above_90f,
      count(*) FILTER (WHERE is_precipitation_usable AND prcp_mm >= 0.254) AS measurable_prcp_days,
      count(*) FILTER (WHERE is_snow_usable AND (snow_mm > 0 OR snow_is_trace)) AS snowfall_days,
      day(last_day(make_date(year, month, 1))) AS expected_calendar_days,
      count(usable_tmax_c) AS usable_tmax_days, count(usable_tmin_c) AS usable_tmin_days,
      count(best_available_tavg_c) AS usable_tavg_days,
      count(prcp_mm) FILTER (WHERE is_precipitation_usable) AS usable_prcp_days,
      count(snow_mm) FILTER (WHERE is_snow_usable) AS usable_snow_days,
      100.0 * count(usable_tmax_c) / day(last_day(make_date(year, month, 1))) AS tmax_completeness_pct,
      100.0 * count(usable_tmin_c) / day(last_day(make_date(year, month, 1))) AS tmin_completeness_pct,
      100.0 * count(best_available_tavg_c) / day(last_day(make_date(year, month, 1))) AS tavg_completeness_pct,
      100.0 * count(prcp_mm) FILTER (WHERE is_precipitation_usable)
        / day(last_day(make_date(year, month, 1))) AS prcp_completeness_pct,
      100.0 * count(snow_mm) FILTER (WHERE is_snow_usable)
        / day(last_day(make_date(year, month, 1))) AS snow_completeness_pct
    FROM daily_metrics GROUP BY station_id, year, month;

    CREATE OR REPLACE VIEW dry_and_freeze_runs AS
    WITH marked AS (
      SELECT *, observation_date
        - row_number() OVER (PARTITION BY station_id, year,
          CASE WHEN is_precipitation_usable AND coalesce(prcp_mm,0) < 0.254 THEN 1 ELSE 0 END
          ORDER BY observation_date)::INTEGER AS dry_group,
        observation_date
        - row_number() OVER (PARTITION BY station_id, year,
          CASE WHEN usable_tmin_c <= 0 THEN 1 ELSE 0 END
          ORDER BY observation_date)::INTEGER AS freeze_group
      FROM daily_metrics
    ), dry AS (
      SELECT station_id, year, max(n) longest_dry
      FROM (SELECT station_id, year, dry_group, count(*) n FROM marked
            WHERE is_precipitation_usable AND coalesce(prcp_mm,0) < 0.254 GROUP BY ALL)
      GROUP BY station_id, year
    ), frozen AS (
      SELECT station_id, year, max(n) longest_freeze
      FROM (SELECT station_id, year, freeze_group, count(*) n FROM marked
            WHERE usable_tmin_c <= 0 GROUP BY ALL) GROUP BY station_id, year
    )
    SELECT coalesce(dry.station_id, frozen.station_id) AS station_id,
           coalesce(dry.year, frozen.year) AS "year", longest_dry, longest_freeze
    FROM dry FULL JOIN frozen USING (station_id, year);

    CREATE OR REPLACE VIEW station_annual_summary AS
    WITH annual AS (
      SELECT station_id, year,
        avg(usable_tmax_c) mean_tmax_c, avg(usable_tmin_c) mean_tmin_c,
        avg(best_available_tavg_c) mean_tavg_c,
        sum(prcp_mm) FILTER (WHERE is_precipitation_usable) total_prcp_mm,
        sum(snow_mm) FILTER (WHERE is_snow_usable) total_snow_mm,
        max(snow_depth_mm) FILTER (WHERE snwd_quality_flag IS NULL) max_snow_depth_mm,
        sum(heating_degree_days_65f) heating_degree_days_65f,
        sum(cooling_degree_days_65f) cooling_degree_days_65f,
        sum(growing_degree_days_50f) growing_degree_days_50f,
        count(*) FILTER (WHERE usable_tmin_c <= 0) days_at_or_below_freezing,
        count(*) FILTER (WHERE usable_tmin_c < -17.7777777778) days_below_0f,
        count(*) FILTER (WHERE usable_tmax_c >= 32.2222222222) days_at_or_above_90f,
        count(*) FILTER (WHERE is_precipitation_usable AND prcp_mm >= 0.254) measurable_prcp_days,
        count(*) FILTER (WHERE is_snow_usable AND (snow_mm > 0 OR snow_is_trace)) snowfall_days,
        CASE WHEN year % 400 = 0 OR (year % 4 = 0 AND year % 100 <> 0) THEN 366 ELSE 365 END expected_calendar_days,
        count(usable_tmax_c) usable_tmax_days, count(usable_tmin_c) usable_tmin_days,
        count(best_available_tavg_c) usable_tavg_days,
        count(prcp_mm) FILTER (WHERE is_precipitation_usable) usable_prcp_days,
        count(snow_mm) FILTER (WHERE is_snow_usable) usable_snow_days,
        arg_max(observation_date, CASE WHEN is_precipitation_usable THEN prcp_mm END) wettest_day,
        max(prcp_mm) FILTER (WHERE is_precipitation_usable) wettest_day_prcp_mm,
        max(snow_mm) FILTER (WHERE is_snow_usable) greatest_daily_snowfall_mm,
        max(usable_tmax_c) hottest_daily_max_c, min(usable_tmin_c) coldest_daily_min_c,
        min(observation_date) FILTER (WHERE month >= 7 AND usable_tmin_c <= 0) first_freeze_date,
        max(observation_date) FILTER (WHERE month <= 6 AND usable_tmin_c <= 0) last_freeze_date
      FROM daily_metrics GROUP BY station_id, year
    )
    SELECT a.*, r.longest_dry AS longest_consecutive_dry_days,
      r.longest_freeze AS longest_consecutive_freeze_days,
      date_diff('day', last_freeze_date, first_freeze_date) AS growing_season_days,
      100.0 * usable_tmax_days / expected_calendar_days AS tmax_completeness_pct,
      100.0 * usable_tmin_days / expected_calendar_days AS tmin_completeness_pct,
      100.0 * usable_tavg_days / expected_calendar_days AS tavg_completeness_pct,
      100.0 * usable_prcp_days / expected_calendar_days AS prcp_completeness_pct,
      100.0 * usable_snow_days / expected_calendar_days AS snow_completeness_pct
    FROM annual a LEFT JOIN dry_and_freeze_runs r USING (station_id, year);

    CREATE OR REPLACE VIEW station_climatology_1991_2020 AS
    WITH eligible AS (
      SELECT * FROM station_monthly_summary WHERE year BETWEEN 1991 AND 2020
    )
    SELECT station_id, month,
      avg(mean_tmax_c) FILTER (WHERE tmax_completeness_pct >= 90) normal_tmax_c,
      avg(mean_tmin_c) FILTER (WHERE tmin_completeness_pct >= 90) normal_tmin_c,
      avg(mean_tavg_c) FILTER (WHERE tavg_completeness_pct >= 90) normal_tavg_c,
      avg(total_prcp_mm) FILTER (WHERE prcp_completeness_pct >= 90) normal_monthly_prcp_mm,
      avg(total_snow_mm) FILTER (WHERE snow_completeness_pct >= 90) normal_monthly_snow_mm,
      avg(heating_degree_days_65f) FILTER (WHERE tavg_completeness_pct >= 90) normal_hdd_65f,
      avg(cooling_degree_days_65f) FILTER (WHERE tavg_completeness_pct >= 90) normal_cdd_65f,
      count(*) FILTER (WHERE tmax_completeness_pct >= 90) tmax_qualifying_years,
      count(*) FILTER (WHERE tmin_completeness_pct >= 90) tmin_qualifying_years,
      count(*) FILTER (WHERE tavg_completeness_pct >= 90) tavg_qualifying_years,
      count(*) FILTER (WHERE prcp_completeness_pct >= 90) prcp_qualifying_years,
      count(*) FILTER (WHERE snow_completeness_pct >= 90) snow_qualifying_years,
      least(tmax_qualifying_years, tmin_qualifying_years, tavg_qualifying_years,
            prcp_qualifying_years) >= 24 AS meets_minimum_coverage
    FROM eligible GROUP BY station_id, month;

    CREATE OR REPLACE VIEW station_monthly_anomalies AS
    SELECT m.station_id, m.year, m.month,
      CASE WHEN c.meets_minimum_coverage THEN m.mean_tavg_c - c.normal_tavg_c END temperature_anomaly_c,
      CASE WHEN c.meets_minimum_coverage THEN m.total_prcp_mm - c.normal_monthly_prcp_mm END precipitation_anomaly_mm,
      c.meets_minimum_coverage
    FROM station_monthly_summary m LEFT JOIN station_climatology_1991_2020 c
      USING (station_id, month);

    CREATE OR REPLACE VIEW station_annual_climatology_1991_2020 AS
    WITH eligible AS (
      SELECT * FROM station_annual_summary WHERE year BETWEEN 1991 AND 2020
    )
    SELECT station_id,
      avg(mean_tmax_c) FILTER (WHERE tmax_completeness_pct >= 90) normal_tmax_c,
      avg(mean_tmin_c) FILTER (WHERE tmin_completeness_pct >= 90) normal_tmin_c,
      avg(mean_tavg_c) FILTER (WHERE tavg_completeness_pct >= 90) normal_tavg_c,
      avg(total_prcp_mm) FILTER (WHERE prcp_completeness_pct >= 90) normal_annual_prcp_mm,
      avg(total_snow_mm) FILTER (WHERE snow_completeness_pct >= 90) normal_annual_snow_mm,
      avg(heating_degree_days_65f) FILTER (WHERE tavg_completeness_pct >= 90) normal_hdd_65f,
      avg(cooling_degree_days_65f) FILTER (WHERE tavg_completeness_pct >= 90) normal_cdd_65f,
      count(*) FILTER (WHERE tmax_completeness_pct >= 90) tmax_qualifying_years,
      count(*) FILTER (WHERE tmin_completeness_pct >= 90) tmin_qualifying_years,
      count(*) FILTER (WHERE tavg_completeness_pct >= 90) tavg_qualifying_years,
      count(*) FILTER (WHERE prcp_completeness_pct >= 90) prcp_qualifying_years,
      count(*) FILTER (WHERE snow_completeness_pct >= 90) snow_qualifying_years,
      least(tmax_qualifying_years, tmin_qualifying_years, tavg_qualifying_years,
            prcp_qualifying_years) >= 24 AS meets_minimum_coverage
    FROM eligible GROUP BY station_id;

    CREATE OR REPLACE VIEW station_data_coverage AS
    SELECT station_id, year, min(observation_date) first_observation_date,
      max(observation_date) last_observation_date, count(*) observed_rows,
      count(usable_tmax_c) usable_tmax_days, count(usable_tmin_c) usable_tmin_days,
      count(best_available_tavg_c) usable_tavg_days,
      count(prcp_mm) FILTER (WHERE is_precipitation_usable) usable_prcp_days,
      count(snow_mm) FILTER (WHERE is_snow_usable) usable_snow_days,
      count(snow_depth_mm) FILTER (WHERE snwd_quality_flag IS NULL) usable_snow_depth_days
    FROM daily_metrics GROUP BY station_id, year;
    """)
    con.close()
    LOG.info("created DuckDB analytics views at %s", paths.database)

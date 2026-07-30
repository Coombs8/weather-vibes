from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest

from weather_vibes.analytics import build_analytics
from weather_vibes.config import Paths
from weather_vibes.conform import build_conformed
from weather_vibes.validate import validate


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def product(tmp_path: Path) -> Paths:
    paths = Paths(tmp_path / "data")
    paths.create()
    shutil.copy(FIXTURES / "ghcnd-stations.txt", paths.raw / "ghcnd-stations.txt")
    shutil.copy(FIXTURES / "USC00200001.csv", paths.station_files / "USC00200001.csv")
    build_conformed(paths)
    build_analytics(paths)
    return paths


def test_units_flags_dates_and_averages(product: Paths) -> None:
    con = duckdb.connect(str(product.database), read_only=True)
    leap = con.execute("""
      SELECT tmax_c, tmin_c, reported_tavg_c, calculated_tavg_c,
             best_available_tavg_c, prcp_mm, prcp_is_trace, snow_quality_flag,
             is_snow_usable, day_of_year
      FROM daily_weather WHERE observation_date = DATE '2020-02-29'
    """).fetchone()
    assert leap == (12.0, 2.0, None, 7.0, 7.0, 0.0, True, "X", False, 60)

    reported = con.execute("""
      SELECT reported_tavg_c, calculated_tavg_c, best_available_tavg_c
      FROM daily_weather WHERE observation_date = DATE '2020-02-28'
    """).fetchone()
    assert reported == (5.0, 5.0, 5.0)


def test_quality_policy_and_aggregations(product: Paths) -> None:
    con = duckdb.connect(str(product.database), read_only=True)
    march = con.execute("""
      SELECT mean_tmax_c, mean_tmin_c, mean_tavg_c, total_prcp_mm,
             heating_degree_days_65f, expected_calendar_days
      FROM station_monthly_summary WHERE year=2020 AND month=3
    """).fetchone()
    assert march[0] is None  # quality-flagged TMAX is excluded
    assert march[1] == -1.0
    assert march[2] == 1.5  # reported TAVG takes precedence
    assert march[3] == 2.5
    assert march[4] == pytest.approx(18.3333333333 - 1.5)
    assert march[5] == 31


def test_validation_and_repeatability(product: Paths) -> None:
    before = duckdb.connect(str(product.database), read_only=True).execute(
        "SELECT station_id, observation_date, tmax_c, ingestion_timestamp FROM daily_weather ORDER BY 1,2"
    ).fetchall()
    assert all(value == 0 for value in validate(product).values())
    build_conformed(product)
    build_analytics(product)
    after = duckdb.connect(str(product.database), read_only=True).execute(
        "SELECT station_id, observation_date, tmax_c FROM daily_weather ORDER BY 1,2"
    ).fetchall()
    assert [(a, b, c) for a, b, c, _ in before] == after


def test_degree_days_freezing_thresholds(product: Paths) -> None:
    con = duckdb.connect(str(product.database), read_only=True)
    result = con.execute("""
      SELECT heating_degree_days_65f, cooling_degree_days_65f, growing_degree_days_50f
      FROM daily_metrics WHERE observation_date=DATE '2020-02-29'
    """).fetchone()
    assert result == pytest.approx((11.3333333333, 0, 0))


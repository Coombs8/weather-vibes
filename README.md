# weather-vibes

An analytics-ready Michigan weather and climate data product built from NOAA
GHCN-Daily. It downloads every station whose current NOAA station metadata has
state `MI`, preserves the source, conforms the six core daily elements to
Parquet, and exposes documented DuckDB analytics views.

## Quick start

Python 3.11 or later is required.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'

# A small real-data run
.venv/bin/weather-vibes --data-dir data run --limit 2

# The complete Michigan product
.venv/bin/weather-vibes --data-dir data run

# Individual stages
.venv/bin/weather-vibes --data-dir data download --workers 6
.venv/bin/weather-vibes --data-dir data build-conformed
.venv/bin/weather-vibes --data-dir data build-analytics
.venv/bin/weather-vibes --data-dir data validate

# Tests need no network
.venv/bin/pytest

# Open with a system DuckDB CLI; otherwise lists the available views
.venv/bin/weather-vibes --data-dir data query
duckdb data/weather.duckdb
```

`--data-dir` may be replaced by `WEATHER_VIBES_DATA_DIR`. A limited download
does not delete previously cached station files; use a fresh data directory for
a strictly limited smoke product.

## Sources

Accessed 2026-07-29:

- Dataset root: <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/>
- NOAA documentation: <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/doc/readme.txt>
- Station metadata: <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/doc/ghcnd-stations.txt>
- Per-station CSV: <https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/>

The downloaded NOAA documentation is retained as `raw/noaa-readme.txt` beside
the data used for a run.

## Architecture and layout

```text
data/
├── raw/
│   ├── ghcnd-stations.txt       # unmodified NOAA station metadata
│   ├── noaa-readme.txt          # documentation used by the run
│   ├── manifest.jsonl           # one auditable entry per download attempt
│   └── stations/*.csv           # unmodified wide NOAA station CSVs
├── conformed/
│   ├── stations.parquet
│   └── daily_weather.parquet
└── weather.duckdb               # reproducible views over Parquet
```

The raw layer uses atomic `.part` files, HTTP range requests for resume,
conditional requests for unchanged files, three attempts with exponential
backoff, and a bounded thread pool. Each manifest record includes URL, UTC
retrieval time, outcome, local path, byte size, SHA-256, and error. Individual
station failures are logged and retained in the manifest without discarding
successful downloads.

The conformed layer is rebuilt entirely from local cached files and never
performs network access. It uses one Zstandard-compressed Parquet file per
table, with 100,000-row groups for daily data. For Michigan this avoids the
tiny-file overhead of station or month partitioning while permitting row-group
pruning by station/date after sorted output. Raw refresh is incremental;
conformed output is a deterministic snapshot rebuild. A future very large
geographic expansion may warrant year partitions.

The analytics database contains views rather than copied data, so rebuilding it
is fast. See [example queries](examples/queries.sql).

## Schemas, grain, and units

`stations` has one row per included station. `daily_weather` has expected grain
`(station_id, observation_date)`. The validation command fails on duplicates,
invalid dates, orphan IDs, non-Michigan metadata, bad coordinate bounds,
negative usable hydrology values, or usable `TMIN > TMAX`.

Canonical units follow NOAA's documentation:

- `TMAX`, `TMIN`, and reported `TAVG`: source tenths °C converted to °C
- `PRCP`: source tenths mm converted to mm
- `SNOW`, `SNWD`: source millimetres, retained as mm

Source values that are absent stay null. Fahrenheit and inch values are not
duplicated in Parquet (`°F = °C × 9/5 + 32`; inches = mm / 25.4).
See [the data dictionary](docs/data_dictionary.md) for column definitions.

### Flags, quality, and trace policy

Every core element retains NOAA's measurement, quality, source, and observation
time attributes as separate columns. The original packed attribute string also
remains recoverable from the unmodified raw CSV.

Any nonblank NOAA quality flag makes that particular element unusable for
analytics. Its numeric value and flags remain in conformed data; `usable_*`
columns and element-level usability booleans prevent accidental mixing.
`is_quality_flagged` indicates any flagged core element on the row. This policy
does not reinterpret individual NOAA quality codes as different severity
levels.

NOAA measurement flag `T` means trace precipitation, snowfall, or snow depth.
The source numeric value (normally zero) is retained and an explicit
`*_is_trace` boolean preserves its meaning. Traces contribute zero to totals
but count as snowfall days. “Measurable precipitation” means at least 0.254 mm
(0.01 inch), so trace does not count as measurable.

### Average temperatures and degree days

`reported_tavg_c` is NOAA TAVG. `calculated_tavg_c` is `(usable TMAX + usable
TMIN) / 2` when both endpoints exist. `best_available_tavg_c` uses usable
reported TAVG first, then the calculated value. A reported average is never
overwritten.

Daily base-65°F heating and cooling degree days use best average temperature:

```text
HDD65 = max(0, 18.333333°C - TAVG)
CDD65 = max(0, TAVG - 18.333333°C)
GDD50 = max(0, TAVG - 10°C)
```

Missing best average produces a missing daily degree-day value and is excluded
from sums; completeness counts show the number of contributing days.

## Analytics methodology

`station_monthly_summary` and `station_annual_summary` expose temperatures,
precipitation/snow totals, snow depth, degree days, threshold-day counts,
expected days, usable counts, and percentages. Expected days use the real
calendar including Gregorian leap years.

Annual dry streaks are consecutive usable days below 0.254 mm precipitation.
Freeze streaks are consecutive days with usable `TMIN <= 0°C`. The annual
freeze convention is last freeze in January–June and first freeze in
July–December of the same calendar year; growing-season length is the number of
days between those dates. It is null where either boundary is absent. This
simple convention is transparent but is not suitable for Southern Hemisphere
stations (which are outside this product).

`station_climatology_1991_2020` and
`station_annual_climatology_1991_2020` calculate product-derived monthly and
annual climatologies, not official NOAA Climate Normals. A station/period needs at least
24 of the 30 years with 90% daily completeness for temperature, precipitation,
and snow independently. Coverage counts are exposed. The combined
`meets_minimum_coverage` requires 24 qualifying years for TMAX, TMIN, TAVG, and
precipitation; anomalies are null when it is false.

`station_monthly_anomalies` subtracts those eligible 1991–2020 monthly
temperature and precipitation baselines. `station_data_coverage` reports yearly
record bounds and usable element counts.

## Decisions and limitations

- Michigan membership comes only from the current `STATE` field, never a
  maintained station list.
- NOAA documents `ghcnd-stations.txt` as ASCII, but the 2026-07-29 file contains
  UTF-8 characters in station names. The parser follows the current file and
  decodes UTF-8.
- Raw wide CSVs preserve non-core elements for later work, but only TMAX, TMIN,
  TAVG, PRCP, SNOW, and SNWD are conformed today.
- Source CSV schemas are unioned by name because stations report different
  element sets.
- GHCN-Daily is updated and periodically reconstructed. Results describe the
  downloaded snapshot, not an immutable vintage.
- A station CSV supplies only dates with some reported element. Completeness
  uses full calendar days, not row counts as the denominator.
- A complete Michigan network run may be sizable and was intentionally not
  performed during repository creation. The exact command is shown above.

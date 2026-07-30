# Data dictionary

## `stations`

Grain: one row per Michigan station included in the local snapshot.

| Column | Type | Meaning |
|---|---|---|
| `station_id` | VARCHAR | NOAA GHCN-Daily station identifier |
| `station_name` | VARCHAR | Name from `ghcnd-stations.txt` |
| `state` | VARCHAR | `MI` |
| `latitude`, `longitude` | DOUBLE | Decimal degrees, WGS84-like geographic coordinates |
| `elevation_m` | DOUBLE | Elevation in metres; NOAA `-999.9` becomes null |
| `gsn_flag` | VARCHAR | NOAA Global Climate Observing System Surface Network flag |
| `hcn_crn_flag` | VARCHAR | NOAA US HCN or Climate Reference Network flag |
| `wmo_id` | VARCHAR | World Meteorological Organization identifier, when present |
| `first_observation_date`, `last_observation_date` | DATE | Bounds found in the cached station CSV |

## `daily_weather`

Grain: one row per `(station_id, observation_date)`.

| Columns | Type | Meaning |
|---|---|---|
| `station_id` | VARCHAR | Foreign key to `stations` |
| `observation_date` | DATE | Calendar observation date |
| `year`, `month`, `day`, `day_of_year` | integers | Calendar projections; day of year handles leap day |
| `tmax_c`, `tmin_c`, `reported_tavg_c` | DOUBLE | NOAA source temperature converted from tenths °C to °C, including flagged values |
| `calculated_tavg_c` | DOUBLE | Mean of usable TMAX and TMIN |
| `best_available_tavg_c` | DOUBLE | Usable reported TAVG, else calculated TAVG |
| `prcp_mm` | DOUBLE | Precipitation converted from tenths mm to mm |
| `snow_mm`, `snow_depth_mm` | DOUBLE | Snowfall and snow depth in source mm |
| `usable_tmax_c`, `usable_tmin_c`, `usable_reported_tavg_c` | DOUBLE | Null when the corresponding NOAA quality flag is nonblank |
| `<element>_measurement_flag` | VARCHAR | NOAA MFLAG, including `T` for trace |
| `<element>_quality_flag` | VARCHAR | NOAA QFLAG; any nonblank value is excluded from analytics |
| `<element>_source_flag` | VARCHAR | NOAA SFLAG identifying data source |
| `<element>_observation_time` | VARCHAR | HHMM observation time if supplied |
| `<element>_is_trace` | BOOLEAN | Measurement flag is `T` |
| `is_quality_flagged` | BOOLEAN | At least one core element has a quality flag |
| `is_temperature_usable` | BOOLEAN | At least one temperature exists and TMAX/TMIN flags are blank |
| `is_precipitation_usable`, `is_snow_usable` | BOOLEAN | Element exists and its quality flag is blank |
| `ingestion_timestamp` | TIMESTAMP | UTC time when this conformed snapshot was produced |

`<element>` is one of `tmax`, `tmin`, `tavg`, `prcp`, `snow`, or `snwd`.

## Analytics views

| View | Grain |
|---|---|
| `daily_metrics` | station/date; adds HDD65, CDD65, and GDD50 |
| `station_monthly_summary` | station/year/month |
| `station_annual_summary` | station/year |
| `station_climatology_1991_2020` | station/calendar month |
| `station_annual_climatology_1991_2020` | station |
| `station_monthly_anomalies` | station/year/month |
| `station_data_coverage` | station/year |

Names and units are explicit in analytics columns: `_c`, `_mm`, `_days`, or
`_pct`. See the README for formulas, completeness, and freeze conventions.

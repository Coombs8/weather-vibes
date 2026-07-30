-- 1. Stations with >=90% usable TMAX and TMIN coverage in every year since 1991.
SELECT c.station_id, s.station_name, min(c.usable_tmax_days / expected.days) AS min_tmax_ratio,
       min(c.usable_tmin_days / expected.days) AS min_tmin_ratio
FROM station_data_coverage c
JOIN stations s USING (station_id)
CROSS JOIN LATERAL (
  SELECT CASE WHEN c.year % 400 = 0 OR (c.year % 4 = 0 AND c.year % 100 <> 0)
              THEN 366.0 ELSE 365.0 END AS days
) expected
WHERE c.year >= 1991 AND c.year < year(current_date)
GROUP BY c.station_id, s.station_name
HAVING min(c.usable_tmax_days / expected.days) >= .9
   AND min(c.usable_tmin_days / expected.days) >= .9
ORDER BY c.station_id;

-- 2. Ten snowiest station-winters (December assigned to the following winter year).
SELECT station_id, CASE WHEN month = 12 THEN year + 1 ELSE year END AS winter_year,
       sum(total_snow_mm) AS snow_mm
FROM station_monthly_summary WHERE month IN (12, 1, 2)
GROUP BY station_id, winter_year ORDER BY snow_mm DESC NULLS LAST LIMIT 10;

-- 3. Annual HDD trend at a station (replace station ID).
SELECT year, heating_degree_days_65f FROM station_annual_summary
WHERE station_id = 'USW00014836' ORDER BY year;

-- 4. Most 90F days in a selected year.
SELECT station_id, days_at_or_above_90f FROM station_annual_summary
WHERE year = 2025 ORDER BY days_at_or_above_90f DESC LIMIT 20;

-- 5. Monthly anomalies within 50 km of Lansing (42.7325, -84.5555).
WITH nearby AS (
  SELECT station_id, 6371 * 2 * asin(sqrt(
    pow(sin(radians(latitude - 42.7325) / 2), 2) +
    cos(radians(42.7325)) * cos(radians(latitude)) *
    pow(sin(radians(longitude - (-84.5555)) / 2), 2))) AS distance_km
  FROM stations
)
SELECT a.*, n.distance_km FROM station_monthly_anomalies a
JOIN nearby n USING (station_id) WHERE n.distance_km <= 50
ORDER BY year DESC, month DESC, distance_km;

-- 6. Nearest station to supplied coordinates; Haversine great-circle distance.
WITH distances AS (
  SELECT station_id, station_name, 6371 * 2 * asin(sqrt(
    pow(sin(radians(latitude - 42.7325) / 2), 2) +
    cos(radians(42.7325)) * cos(radians(latitude)) *
    pow(sin(radians(longitude - (-84.5555)) / 2), 2))) AS distance_km
  FROM stations
)
SELECT * FROM distances ORDER BY distance_km LIMIT 1;


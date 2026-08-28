-- Backtest, step 3 of 3: score the forecast against what actually happened.
--
-- A test month is FLAGGED when TimesFM's 90th-percentile forecast for that
-- series crosses the enforceable limit in force that month. A test month
-- is an EXCEEDANCE when the facility actually reported a value above that
-- limit. Both sides use enforceable limits only; the forecast never saw
-- any test-window data.
--
-- Lead time, defined conservatively: the flag for month M existed no later
-- than the first day of M (the forecast was issued at the 2025-03 cutoff,
-- so usually earlier). The exceedance became visible to anyone when the
-- monthly report reached the regulator (value_received_date). Lead =
-- value_received_date − first day of M, in days.
--
-- Every number in the Finding (video, README, Devpost) comes from the
-- `finding` table this script writes. Nothing is typed by hand.

CREATE OR REPLACE TABLE steward_npdes.bt_scored AS
SELECT
  t.series_id,
  t.external_permit_nmbr,
  t.parameter_code,
  t.parameter_desc,
  t.month,
  t.value,
  t.limit_value,
  t.exceeded,
  t.exceedance_received_date,
  f.forecast_value,
  f.p90,
  f.p90 >= t.limit_value AS flagged,
  DATE_DIFF(t.exceedance_received_date, t.month, DAY) AS lead_days
FROM steward_npdes.bt_truth t
JOIN steward_npdes.bt_forecast f USING (series_id, month);

CREATE OR REPLACE TABLE steward_npdes.finding AS
SELECT
  CURRENT_DATE() AS computed_on,
  CONCAT(
    'EPA ICIS-NPDES public record ',
    (SELECT FORMAT_DATE('%Y-%m', MIN(month)) FROM steward_npdes.bt_series), ' → ',
    (SELECT FORMAT_DATE('%Y-%m', MAX(month)) FROM steward_npdes.bt_truth),
    '; POTW effluent, enforceable limits only'
  ) AS corpus,
  (SELECT COUNT(*) FROM steward_npdes.bt_series)
    + (SELECT COUNT(*) FROM steward_npdes.bt_truth) AS reported_values,
  COUNT(DISTINCT external_permit_nmbr) AS facilities,
  COUNT(DISTINCT series_id) AS series,
  COUNT(*) AS test_months,
  COUNTIF(exceeded) AS exceedance_months,
  COUNTIF(flagged) AS flagged_months,
  COUNTIF(exceeded AND flagged) AS caught,
  ROUND(100 * COUNTIF(exceeded AND flagged) / NULLIF(COUNTIF(exceeded), 0), 1)
    AS recall_pct,
  ROUND(100 * COUNTIF(exceeded AND flagged) / NULLIF(COUNTIF(flagged), 0), 1)
    AS precision_pct,
  APPROX_QUANTILES(IF(exceeded AND flagged, lead_days, NULL), 2)[OFFSET(1)]
    AS median_lead_days
FROM steward_npdes.bt_scored;

CREATE OR REPLACE TABLE steward_npdes.finding_by_parameter AS
SELECT
  parameter_code,
  ANY_VALUE(parameter_desc) AS parameter_desc,
  COUNT(DISTINCT external_permit_nmbr) AS facilities,
  COUNTIF(exceeded) AS exceedance_months,
  COUNTIF(exceeded AND flagged) AS caught,
  ROUND(100 * COUNTIF(exceeded AND flagged) / NULLIF(COUNTIF(exceeded), 0), 1)
    AS recall_pct,
  APPROX_QUANTILES(IF(exceeded AND flagged, lead_days, NULL), 2)[OFFSET(1)]
    AS median_lead_days
FROM steward_npdes.bt_scored
GROUP BY parameter_code
HAVING COUNTIF(exceeded) >= 100
ORDER BY exceedance_months DESC;

SELECT * FROM steward_npdes.finding;

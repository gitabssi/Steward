-- Backtest, step 1 of 3: build the series and the ground truth.
--
-- Population: municipal treatment works (POTW per ICIS), effluent gross
-- monitoring (monitoring_location_code = '1'), ENFORCEABLE limits only
-- (limit_type_code = 'ENF' — never alert/benchmark thresholds), upper-bound
-- limits (qualifier '<=' or '<'), monthly reporters.
--
-- One series = one facility × outfall × parameter × statistical base.
-- Training window: months up to 2025-03 (up to 30 monthly points from the
-- FY2023–FY2025 extract; FY2020–22 extend history when loaded).
-- Test window:     2025-04 .. 2025-09 — six months the model never sees.
--
-- Ground truth for a test month: the facility actually reported a value
-- above its enforceable limit that month (dmr_value > limit_value, both in
-- EPA standard units). value_received_date records when that number
-- actually reached the regulator — the lead-time metric is built on it.

DECLARE train_end DATE DEFAULT DATE '2025-03-31';
DECLARE test_end DATE DEFAULT DATE '2025-09-30';

CREATE SCHEMA IF NOT EXISTS steward_npdes;

-- POTW permit universe (any permit version flagged POTW).
CREATE OR REPLACE TABLE steward_npdes.bt_potw AS
SELECT DISTINCT external_permit_nmbr
FROM steward_npdes.permits
WHERE facility_type_indicator = 'POTW';

-- Candidate rows: every usable effluent measurement with its limit.
CREATE OR REPLACE TEMP TABLE candidate AS
SELECT
  CONCAT(d.external_permit_nmbr, '|', d.perm_feature_nmbr, '|',
         d.parameter_code, '|', d.statistical_base_code) AS series_id,
  d.external_permit_nmbr,
  d.parameter_code,
  ANY_VALUE(d.parameter_desc) AS parameter_desc,
  DATE_TRUNC(d.monitoring_period_end_date, MONTH) AS month,
  AVG(d.dmr_value_standard_units) AS value,
  -- The limit in force that month (constant within a month per series).
  MAX(d.limit_value_standard_units) AS limit_value,
  LOGICAL_OR(d.dmr_value_standard_units > d.limit_value_standard_units) AS exceeded,
  LOGICAL_OR(d.violation_code = 'E90') AS exceeded_epa_flag,
  MIN(IF(d.dmr_value_standard_units > d.limit_value_standard_units,
         d.value_received_date, NULL)) AS exceedance_received_date
FROM steward_npdes.dmrs d
JOIN steward_npdes.bt_potw p USING (external_permit_nmbr)
WHERE d.limit_type_code = 'ENF'
  AND d.limit_value_qualifier_code IN ('<=', '<')
  AND d.limit_value_standard_units IS NOT NULL
  AND d.limit_value_standard_units > 0
  AND d.dmr_value_standard_units IS NOT NULL
  AND d.monitoring_location_code = '1'  -- effluent gross
  AND d.monitoring_period_end_date <= test_end
GROUP BY series_id, d.external_permit_nmbr, d.parameter_code, month;

-- Monthly reporters with enough recent history to forecast honestly:
-- at least 24 of the 30 months ending at the cutoff. (Older loaded years
-- extend each eligible series' context; they do not relax eligibility —
-- a quarterly reporter cannot qualify by accumulating years.)
CREATE OR REPLACE TEMP TABLE eligible AS
SELECT series_id
FROM candidate
WHERE month BETWEEN DATE_SUB(train_end, INTERVAL 30 MONTH) AND train_end
GROUP BY series_id
HAVING COUNT(DISTINCT month) >= 24;

CREATE OR REPLACE TABLE steward_npdes.bt_series AS
SELECT c.series_id, c.month, c.value
FROM candidate c
JOIN eligible USING (series_id)
WHERE c.month <= train_end;

CREATE OR REPLACE TABLE steward_npdes.bt_truth AS
SELECT
  c.series_id,
  c.external_permit_nmbr,
  c.parameter_code,
  c.parameter_desc,
  c.month,
  c.value,
  c.limit_value,
  c.exceeded,
  c.exceeded_epa_flag,
  c.exceedance_received_date
FROM candidate c
JOIN eligible USING (series_id)
WHERE c.month > train_end;

SELECT
  (SELECT COUNT(DISTINCT series_id) FROM steward_npdes.bt_series) AS series,
  (SELECT COUNT(DISTINCT SPLIT(series_id, '|')[0]) FROM steward_npdes.bt_series) AS facilities,
  (SELECT COUNT(*) FROM steward_npdes.bt_series) AS training_rows,
  (SELECT COUNT(*) FROM steward_npdes.bt_truth) AS test_rows,
  (SELECT COUNTIF(exceeded) FROM steward_npdes.bt_truth) AS exceedance_months;

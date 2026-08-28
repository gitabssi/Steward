-- Backtest, step 2 of 3: forecast every series with TimesFM.
--
-- AI.FORECAST is BigQuery ML's serverless interface to TimesFM: no
-- endpoint, no training job — the foundation model reads each monthly
-- series (≥24 points ending 2025-03) and emits six months of forecasts
-- with a prediction interval.
--
-- confidence_level 0.8 makes the interval's upper bound the 90th
-- percentile. The exceedance flag deliberately uses that quantile, not
-- the point forecast: the question a permit answers is not "what is the
-- expected value" but "how likely is the bad tail" — a parameter whose
-- P90 crosses the enforceable limit is a parameter worth an operator's
-- attention a month early.

CREATE OR REPLACE TABLE steward_npdes.bt_forecast AS
SELECT
  series_id,
  DATE(forecast_timestamp) AS month,
  forecast_value,
  prediction_interval_lower_bound AS p10,
  prediction_interval_upper_bound AS p90
FROM AI.FORECAST(
  (SELECT series_id, month, value FROM steward_npdes.bt_series),
  data_col => 'value',
  timestamp_col => 'month',
  id_cols => ['series_id'],
  horizon => 6,
  confidence_level => 0.8
);

SELECT COUNT(DISTINCT series_id) AS series_forecast,
       COUNT(*) AS forecast_rows
FROM steward_npdes.bt_forecast;

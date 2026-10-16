-- ============================================================================
-- FraudPulse BI : Business Views (reusable reporting layer)
-- These views encode the "business definitions" used across the
-- dashboard and the static analytics report, so every KPI is computed once
-- with a single definition.
-- ============================================================================

USE fraudpulse_bi;

-- ---------------------------------------------------------------------------
-- View 1 : portfolio-level KPIs
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_fraud_summary;
CREATE VIEW v_fraud_summary AS
SELECT
    COUNT(*)                                                    AS total_transactions,
    SUM(amount)                                                 AS total_amount,
    SUM(is_fraud)                                               AS fraud_transactions,
    SUM(is_fraud * amount)                                      AS fraud_amount,
    ROUND(SUM(is_fraud) / COUNT(*) * 100, 4)                    AS fraud_rate_pct,
    ROUND(SUM(is_fraud * amount) / NULLIF(SUM(amount), 0) * 100, 4) AS fraud_amount_rate_pct,
    SUM(is_flagged_fraud)                                       AS flagged_fraud_transactions,
    ROUND(SUM(is_flagged_fraud) / NULLIF(SUM(is_fraud), 0) * 100, 2) AS fraud_detection_coverage_pct
FROM fact_transaction;

-- ---------------------------------------------------------------------------
-- View 2 : fraud profile by transaction type
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_fraud_by_type;
CREATE VIEW v_fraud_by_type AS
SELECT
    t.type_name,
    t.risk_level,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct,
    SUM(f.amount)                                   AS total_amount,
    SUM(f.is_fraud * f.amount)                      AS fraud_amount
FROM fact_transaction f
JOIN dim_transaction_type t USING (type_id)
GROUP BY t.type_name, t.risk_level
ORDER BY fraud_count DESC;

-- ---------------------------------------------------------------------------
-- View 3 : fraud by hour of day (intraday pattern)
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_fraud_by_hour;
CREATE VIEW v_fraud_by_hour AS
SELECT
    d.hour_of_day,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct,
    SUM(f.is_fraud * f.amount)                      AS fraud_amount
FROM fact_transaction f
JOIN dim_time_step d USING (step)
GROUP BY d.hour_of_day
ORDER BY d.hour_of_day;

-- ---------------------------------------------------------------------------
-- View 4 : fraud by day of the simulation (30-day trend)
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_fraud_by_day;
CREATE VIEW v_fraud_by_day AS
SELECT
    d.day_of_month,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct,
    SUM(f.is_fraud * f.amount)                      AS fraud_amount
FROM fact_transaction f
JOIN dim_time_step d USING (step)
GROUP BY d.day_of_month
ORDER BY d.day_of_month;

-- ---------------------------------------------------------------------------
-- View 5 : fraud by amount band
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_fraud_by_amount_bucket;
CREATE VIEW v_fraud_by_amount_bucket AS
SELECT
    f.amount_bucket,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct,
    SUM(f.is_fraud * f.amount)                      AS fraud_amount
FROM fact_transaction f
GROUP BY f.amount_bucket
ORDER BY MIN(f.amount);

-- ---------------------------------------------------------------------------
-- View 6 : balance-inconsistency vs fraud cross tab
--   (data-quality anomaly signal, proven to correlate with fraud in PaySim)
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_balance_inconsistency;
CREATE VIEW v_balance_inconsistency AS
SELECT
    orig_balance_inconsistent,
    dest_balance_inconsistent,
    COUNT(*)                                        AS transaction_count,
    SUM(is_fraud)                                   AS fraud_count,
    ROUND(SUM(is_fraud) / COUNT(*) * 100, 3)        AS fraud_rate_pct
FROM fact_transaction
GROUP BY orig_balance_inconsistent, dest_balance_inconsistent
ORDER BY orig_balance_inconsistent DESC, dest_balance_inconsistent DESC;

-- ---------------------------------------------------------------------------
-- View 7 : top risky originator accounts (repeat offenders)
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_top_risk_customers;
CREATE VIEW v_top_risk_customers AS
SELECT
    name_orig                                       AS customer_id,
    COUNT(*)                                        AS transaction_count,
    SUM(is_fraud)                                   AS fraud_count,
    ROUND(SUM(is_fraud) / COUNT(*) * 100, 2)        AS fraud_rate_pct,
    SUM(is_fraud * amount)                          AS fraud_amount
FROM fact_transaction
GROUP BY name_orig
HAVING fraud_count > 0
ORDER BY fraud_count DESC
LIMIT 50;

-- ============================================================================
-- End of views
-- ============================================================================

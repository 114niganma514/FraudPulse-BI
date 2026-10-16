-- ============================================================================
-- FraudPulse BI : Analytics Query Pack
-- ----------------------------------------------------------------------------
-- Each block is labelled with:
--     -- @query <output_name>
-- and is executed by scripts/04_run_analytics.py which saves the result set
-- to output/tables/<output_name>.csv and feeds the static HTML report.
-- Every query carries its business question and the KPI definition (business definition).
-- ============================================================================

USE fraudpulse_bi;

-- ============================================================================
-- @query q01_portfolio_kpis
-- Business question : What is the overall size of the payment portfolio and
--                     how material is the fraud problem?
-- KPI definitions  : fraud rate (count)  = fraud txns / all txns
--                    fraud amount rate   = fraud amount / total amount
--                    detection coverage  = flagged fraud / actual fraud
-- ============================================================================
SELECT
    COUNT(*)                                        AS total_transactions,
    ROUND(SUM(amount), 2)                           AS total_amount,
    SUM(is_fraud)                                   AS fraud_transactions,
    ROUND(SUM(is_fraud * amount), 2)                AS fraud_amount,
    ROUND(SUM(is_fraud) / COUNT(*) * 100, 4)        AS fraud_rate_pct,
    ROUND(SUM(is_fraud * amount) / SUM(amount) * 100, 4) AS fraud_amount_rate_pct,
    SUM(is_flagged_fraud)                           AS flagged_fraud,
    ROUND(SUM(is_flagged_fraud) / NULLIF(SUM(is_fraud), 0) * 100, 2) AS detection_coverage_pct
FROM fact_transaction;

-- ============================================================================
-- @query q02_fraud_by_type
-- Business question : Which transaction channels carry the fraud risk?
-- Expected insight : TRANSFER & CASH_OUT concentrate almost all fraud.
-- ============================================================================
SELECT
    t.type_name,
    t.risk_level,
    COUNT(*)                                        AS transaction_count,
    ROUND(SUM(f.amount), 2)                         AS total_amount,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud * f.amount), 2)            AS fraud_amount,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct,
    ROUND(SUM(f.is_fraud) / NULLIF((SELECT SUM(is_fraud) FROM fact_transaction), 0) * 100, 2) AS fraud_share_pct
FROM fact_transaction f
JOIN dim_transaction_type t USING (type_id)
GROUP BY t.type_name, t.risk_level
ORDER BY fraud_count DESC;

-- ============================================================================
-- @query q03_fraud_by_hour
-- Business question : Does fraud spike at specific hours of the day?
-- ============================================================================
SELECT
    d.hour_of_day,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct,
    ROUND(SUM(f.is_fraud * f.amount), 2)            AS fraud_amount
FROM fact_transaction f
JOIN dim_time_step d USING (step)
GROUP BY d.hour_of_day
ORDER BY d.hour_of_day;

-- ============================================================================
-- @query q04_fraud_by_day
-- Business question : How does fraud evolve over the 30-day window?
-- ============================================================================
SELECT
    d.day_of_month,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct,
    ROUND(SUM(f.is_fraud * f.amount), 2)            AS fraud_amount
FROM fact_transaction f
JOIN dim_time_step d USING (step)
GROUP BY d.day_of_month
ORDER BY d.day_of_month;

-- ============================================================================
-- @query q05_fraud_by_amount_bucket
-- Business question : Is fraud concentrated in high-value or low-value txns?
-- ============================================================================
SELECT
    f.amount_bucket,
    COUNT(*)                                        AS transaction_count,
    ROUND(SUM(f.amount), 2)                         AS total_amount,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud * f.amount), 2)            AS fraud_amount,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct,
    ROUND(AVG(CASE WHEN f.is_fraud = 1 THEN f.amount END), 2) AS avg_fraud_amount
FROM fact_transaction f
GROUP BY f.amount_bucket
ORDER BY MIN(f.amount);

-- ============================================================================
-- @query q06_avg_amount_fraud_vs_legit
-- Business question : Are fraudulent transactions bigger on average?
-- Median is computed with a ROW_NUMBER window function because MySQL 8 does
-- not ship a PERCENTILE_CONT aggregate.
-- ============================================================================
WITH ranked AS (
    SELECT
        is_fraud,
        amount,
        ROW_NUMBER() OVER (PARTITION BY is_fraud ORDER BY amount) AS rn,
        COUNT(*)     OVER (PARTITION BY is_fraud)                AS cnt
    FROM fact_transaction
)
SELECT
    is_fraud,
    COUNT(*)                                        AS transaction_count,
    ROUND(AVG(amount), 2)                           AS avg_amount,
    ROUND(MIN(amount), 2)                           AS min_amount,
    ROUND(MAX(amount), 2)                           AS max_amount,
    ROUND(AVG(CASE WHEN rn IN (FLOOR((cnt + 1) / 2), CEIL((cnt + 1) / 2))
                   THEN amount END), 2)             AS median_amount
FROM ranked
GROUP BY is_fraud
ORDER BY is_fraud DESC;

-- ============================================================================
-- @query q07_balance_inconsistency
-- Business question : Does a broken balance book-keeping correlate with fraud?
-- Insight          : balance anomalies are a cheap, high-signal rule feature.
-- ============================================================================
SELECT
    orig_balance_inconsistent,
    dest_balance_inconsistent,
    COUNT(*)                                        AS transaction_count,
    SUM(is_fraud)                                   AS fraud_count,
    ROUND(SUM(is_fraud) / COUNT(*) * 100, 3)        AS fraud_rate_pct
FROM fact_transaction
GROUP BY orig_balance_inconsistent, dest_balance_inconsistent
ORDER BY orig_balance_inconsistent DESC, dest_balance_inconsistent DESC;

-- ============================================================================
-- @query q08_flagged_vs_actual_fraud
-- Business question : How good is the legacy rule (flag if amount > 200,000
--                     in a TRANSFER) at catching real fraud?
-- ============================================================================
SELECT
    is_fraud,
    is_flagged_fraud,
    COUNT(*)                                        AS transaction_count,
    ROUND(SUM(amount), 2)                           AS total_amount
FROM fact_transaction
GROUP BY is_fraud, is_flagged_fraud
ORDER BY is_fraud DESC, is_flagged_fraud DESC;

-- ============================================================================
-- @query q09_top_risk_customers
-- Business question : Which originator accounts are repeat offenders?
-- (Window function: rank customers by fraud count, keep top 20)
-- ============================================================================
WITH customer_risk AS (
    SELECT
        name_orig,
        COUNT(*)                                                    AS transaction_count,
        SUM(is_fraud)                                               AS fraud_count,
        ROUND(SUM(is_fraud) / COUNT(*) * 100, 2)                    AS fraud_rate_pct,
        ROUND(SUM(is_fraud * amount), 2)                            AS fraud_amount
    FROM fact_transaction
    GROUP BY name_orig
    HAVING SUM(is_fraud) > 0
)
SELECT *
FROM customer_risk
ORDER BY fraud_count DESC, fraud_amount DESC
LIMIT 20;

-- ============================================================================
-- @query q10_top_fraud_destinations
-- Business question : Which beneficiary accounts receive the stolen funds?
-- ============================================================================
SELECT
    name_dest,
    COUNT(*)                                        AS fraud_transactions,
    ROUND(SUM(amount), 2)                           AS fraud_amount,
    ROUND(AVG(amount), 2)                           AS avg_fraud_amount
FROM fact_transaction
WHERE is_fraud = 1
GROUP BY name_dest
ORDER BY fraud_amount DESC
LIMIT 20;

-- ============================================================================
-- @query q11_amount_concentration
-- Business question : What share of fraud value sits in the biggest 1% of
--                     fraudulent transactions?
-- ============================================================================
WITH fraud_amounts AS (
    SELECT amount, is_fraud
    FROM fact_transaction
    WHERE is_fraud = 1
),
ranked AS (
    SELECT
        amount,
        SUM(amount) OVER ()                                 AS total_fraud_amount,
        PERCENT_RANK() OVER (ORDER BY amount DESC)          AS pct_rank
    FROM fraud_amounts
)
SELECT
    ROUND(SUM(amount), 2) AS top_1pct_fraud_amount,
    ROUND(MAX(total_fraud_amount), 2) AS total_fraud_amount,
    ROUND(SUM(amount) / MAX(total_fraud_amount) * 100, 2) AS share_pct
FROM ranked
WHERE pct_rank <= 0.01;

-- ============================================================================
-- @query q12_fraud_by_time_bucket_peak
-- Business question : Are fraud rates higher in peak hours?
-- ============================================================================
SELECT
    d.time_bucket,
    d.is_peak_hour,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct
FROM fact_transaction f
JOIN dim_time_step d USING (step)
GROUP BY d.time_bucket, d.is_peak_hour
ORDER BY fraud_rate_pct DESC;

-- ============================================================================
-- @query q13_high_value_fraud_bins
-- Business question : Where should manual-review resources be targeted?
-- (fraud rate by amount band restricted to the 5 transaction types)
-- ============================================================================
SELECT
    t.type_name,
    f.amount_bucket,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 2)      AS fraud_rate_pct
FROM fact_transaction f
JOIN dim_transaction_type t USING (type_id)
WHERE f.is_fraud = 1 OR f.amount >= 10000
GROUP BY t.type_name, f.amount_bucket
ORDER BY fraud_count DESC
LIMIT 30;

-- ============================================================================
-- @query q14_customer_single_shot_fraud
-- Business question : Do fraudsters typically strike once or repeatedly?
-- (distribution of fraud count per customer - behavioral fingerprint)
-- ============================================================================
WITH per_customer AS (
    SELECT
        name_orig,
        SUM(is_fraud) AS fraud_txns,
        COUNT(*)      AS total_txns
    FROM fact_transaction
    GROUP BY name_orig
)
SELECT
    fraud_txns,
    COUNT(*)                                        AS customer_count,
    ROUND(AVG(total_txns), 2)                       AS avg_total_txns
FROM per_customer
GROUP BY fraud_txns
ORDER BY fraud_txns;

-- ============================================================================
-- @query q15_volume_mix
-- Business question : What is the transaction mix by channel (context for
--                     interpreting fraud rates)?
-- ============================================================================
SELECT
    t.type_name,
    COUNT(*)                                        AS transaction_count,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER () * 100, 2) AS volume_share_pct,
    ROUND(SUM(f.amount), 2)                         AS total_amount
FROM fact_transaction f
JOIN dim_transaction_type t USING (type_id)
GROUP BY t.type_name
ORDER BY transaction_count DESC;

-- ============================================================================
-- @query q16_fraud_by_orig_zero_balance
-- Business question : Do fraudulent transactions originate from accounts
--                     with NO starting balance (money created from nothing)?
-- Insight          : this is the classic PaySim fraud signature and a far
--                    stronger cheap signal than the generic mismatch flag.
-- ============================================================================
SELECT
    CASE WHEN f.oldbalance_org = 0 THEN 'zero' ELSE 'positive' END AS orig_balance_state,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct,
    ROUND(SUM(f.is_fraud * f.amount), 2)            AS fraud_amount
FROM fact_transaction f
GROUP BY orig_balance_state
ORDER BY fraud_count DESC;

-- ============================================================================
-- @query q17_fraud_zero_balance_by_type
-- Business question : Where exactly does zero-balance fraud concentrate?
-- ============================================================================
SELECT
    t.type_name,
    CASE WHEN f.oldbalance_org = 0 THEN 'zero' ELSE 'positive' END AS orig_balance_state,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 3)      AS fraud_rate_pct
FROM fact_transaction f
JOIN dim_transaction_type t ON f.type_id = t.type_id
GROUP BY t.type_name, orig_balance_state
HAVING fraud_count > 0
ORDER BY fraud_count DESC;

-- ============================================================================
-- @query q18_full_balance_send_rule
-- Business question : Can ONE cheap rule flag fraud with high precision?
-- Insight (headline finding) : when oldbalance_org = amount (the sender
--   sends the exact full account balance, leaving 0), the transaction is
--   fraudulent in ~100% of cases. Captures ~98% of all fraud.
-- ============================================================================
SELECT
    (f.oldbalance_org = f.amount) AS full_balance_send,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 2)      AS fraud_rate_pct,
    ROUND(SUM(f.is_fraud * f.amount), 2)            AS fraud_amount
FROM fact_transaction f
GROUP BY full_balance_send
ORDER BY full_balance_send DESC;

-- ============================================================================
-- @query q19_full_balance_send_by_type
-- Business question : Which channels does the full-balance rule cover?
-- ============================================================================
SELECT
    t.type_name,
    (f.oldbalance_org = f.amount) AS full_balance_send,
    COUNT(*)                                        AS transaction_count,
    SUM(f.is_fraud)                                 AS fraud_count,
    ROUND(SUM(f.is_fraud) / COUNT(*) * 100, 2)      AS fraud_rate_pct
FROM fact_transaction f
JOIN dim_transaction_type t ON f.type_id = t.type_id
GROUP BY t.type_name, full_balance_send
HAVING fraud_count > 0
ORDER BY fraud_count DESC;

-- ============================================================================
-- End of analytics query pack
-- ============================================================================

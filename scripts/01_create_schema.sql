-- ============================================================================
-- FraudPulse BI : SQL Data Warehouse Schema (MySQL 8.0)
-- Database  : fraudpulse_bi
-- Purpose   : Star-schema warehouse for PaySim mobile-payment fraud analytics
-- Author    : FraudPulse BI Project
-- ============================================================================

CREATE DATABASE IF NOT EXISTS fraudpulse_bi
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE fraudpulse_bi;

-- Allow idempotent re-runs: disable FK checks while tables are dropped so
-- child tables created by a previous run do not block dimension drops.
SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------------------
-- 1. Dimension : transaction type
--    Business knowledge: in the PaySim simulation, fraud only occurs in
--    TRANSFER and CASH_OUT operations -> used to encode a risk-level hint.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS dim_transaction_type;
CREATE TABLE dim_transaction_type (
    type_id      TINYINT UNSIGNED NOT NULL AUTO_INCREMENT,
    type_name    VARCHAR(20)      NOT NULL,
    risk_level   VARCHAR(20)      NOT NULL DEFAULT 'LOW',
    description  VARCHAR(120)     NULL,
    PRIMARY KEY (type_id),
    UNIQUE KEY uk_type_name (type_name)
) ENGINE=InnoDB;

INSERT INTO dim_transaction_type (type_name, risk_level, description) VALUES
    ('PAYMENT',  'LOW',    'Payment for a service or bill'),
    ('TRANSFER', 'HIGH',   'Transfer between accounts (fraud-prone)'),
    ('CASH_OUT', 'HIGH',   'Cash withdrawal via agent (fraud-prone)'),
    ('DEBIT',    'LOW',    'Debit / account deduction'),
    ('CASH_IN',  'MEDIUM', 'Cash deposit into account');

-- ---------------------------------------------------------------------------
-- 2. Dimension : time (step -> calendar-like attributes)
--    PaySim "step" = one hour of simulated time. 30 days x 24h = 720 steps
--    (some logs extend to 743). Attributes let the dashboard aggregate by
--    hour-of-day, day-of-week and peak/off-peak windows.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS dim_time_step;
CREATE TABLE dim_time_step (
    step           SMALLINT UNSIGNED NOT NULL,
    hour_of_day    TINYINT UNSIGNED NOT NULL,
    day_of_month   TINYINT UNSIGNED NOT NULL,
    day_of_week    TINYINT UNSIGNED NOT NULL,
    time_bucket    VARCHAR(20)      NOT NULL,
    is_peak_hour   TINYINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (step),
    KEY idx_hod (hour_of_day)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 3. Fact table : transactions (6.36M rows)
--    Degenerate dimensions (customer IDs) kept in the fact to avoid giant
--    dimension tables; balance columns enable data-quality / anomaly checks.
--    Derived flags computed at ETL time:
--      * orig_balance_inconsistent : old - amount != new (impossible money
--        creation) => classic fraud signal in PaySim
--      * dest_balance_inconsistent : new != old + amount
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS fact_transaction;
CREATE TABLE fact_transaction (
    transaction_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    step                     SMALLINT UNSIGNED NOT NULL,
    type_id                  TINYINT UNSIGNED NOT NULL,
    amount                   DECIMAL(15,2)    NOT NULL,
    name_orig                VARCHAR(30)      NOT NULL,
    oldbalance_org           DECIMAL(15,2)    NOT NULL,
    newbalance_orig          DECIMAL(15,2)    NOT NULL,
    name_dest                VARCHAR(30)      NOT NULL,
    oldbalance_dest          DECIMAL(15,2)    NOT NULL,
    newbalance_dest          DECIMAL(15,2)    NOT NULL,
    is_fraud                 TINYINT UNSIGNED NOT NULL DEFAULT 0,
    is_flagged_fraud         TINYINT UNSIGNED NOT NULL DEFAULT 0,
    orig_balance_inconsistent TINYINT UNSIGNED NOT NULL DEFAULT 0,
    dest_balance_inconsistent TINYINT UNSIGNED NOT NULL DEFAULT 0,
    amount_bucket            VARCHAR(20)      NOT NULL DEFAULT 'Medium (1k-10k)',
    PRIMARY KEY (transaction_id),
    KEY idx_step        (step),
    KEY idx_type        (type_id),
    KEY idx_name_orig   (name_orig),
    KEY idx_name_dest   (name_dest),
    KEY idx_is_fraud    (is_fraud),
    KEY idx_amount      (amount),
    KEY idx_type_fraud  (type_id, is_fraud),
    KEY idx_step_fraud  (step, is_fraud),
    KEY idx_orig_inc    (orig_balance_inconsistent, is_fraud),
    CONSTRAINT fk_fact_type FOREIGN KEY (type_id) REFERENCES dim_transaction_type (type_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 4. Populate the time dimension (independent of the fact table)
-- ---------------------------------------------------------------------------
DELETE FROM dim_time_step;
INSERT INTO dim_time_step (step, hour_of_day, day_of_month, day_of_week, time_bucket, is_peak_hour)
WITH RECURSIVE seq AS (
    SELECT 1 AS n
    UNION ALL
    SELECT n + 1 FROM seq WHERE n < 744
)
SELECT
    n                                                         AS step,
    ((n - 1) % 24)                                            AS hour_of_day,
    (((n - 1) DIV 24) + 1)                                    AS day_of_month,
    ((((n - 1) DIV 24)) % 7)                                  AS day_of_week,
    CASE
        WHEN ((n - 1) % 24) BETWEEN 0 AND 5  THEN 'Night'
        WHEN ((n - 1) % 24) BETWEEN 6 AND 11 THEN 'Morning'
        WHEN ((n - 1) % 24) BETWEEN 12 AND 17 THEN 'Afternoon'
        WHEN ((n - 1) % 24) BETWEEN 18 AND 21 THEN 'Evening'
        ELSE 'Late Evening'
    END                                                       AS time_bucket,
    CASE WHEN ((n - 1) % 24) BETWEEN 9 AND 21 THEN 1 ELSE 0 END AS is_peak_hour
FROM seq;

-- ============================================================================
-- End of schema script
-- ============================================================================
SET FOREIGN_KEY_CHECKS = 1;

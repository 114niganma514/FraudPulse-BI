# FraudPulse BI
## SQL Data Warehouse & BI Dashboard for Mobile Payment Fraud Analytics

**Project Report · English Version**

| Field | Detail |
|---|---|
| Project name | FraudPulse BI |
| Category | SQL · Data Warehousing · Business Intelligence (Risk Control) |
| Database | MySQL 8.0 (real server, port 3306, database `fraudpulse_bi`) |
| Dataset | PaySim mobile-payment transactions (public, 6.36M rows) |
| BI stack | Streamlit + Plotly (interactive) · static HTML report |
| Author | Liang Jiayi |
| Date | September 2026 |

---

## 1. Executive Summary

FraudPulse BI is an end-to-end risk-analytics platform built on a **real MySQL
database** that turns a large, raw mobile-payment log into a dimensional
warehouse, a set of **business-defined fraud KPIs**, and a self-service BI
dashboard. The project demonstrates the entire SQL + BI workflow a risk
analytics or data-engineering role expects: schema design, ETL bulk loading,
window-function analytics, business-view modeling, and interactive reporting.

The headline business finding:

> **When a sender transfers their exact full account balance
> (`oldbalance_org = amount`), the transaction is fraudulent in 100% of cases —
> a single cheap SQL rule captures 97.8% of all fraud.**

Fraud is almost exclusively concentrated in **TRANSFER** and **CASH_OUT**
channels, spikes in **night / off-peak hours**, and the legacy rule-based
detector catches only **0.19%** of actual fraud.

---

## 2. Business Context & Objective

Mobile money platforms face a high-volume, low-signal fraud problem: hundreds
of thousands of transactions flow every hour and only ~0.13% are fraudulent.
The business questions this project answers:

1. **How big is the problem?** Portfolio-level fraud rate by count and by value.
2. **Where does fraud hide?** Channel, time-of-day, day, amount band.
3. **Who are the bad actors?** Originator and beneficiary accounts.
4. **Can we detect it with cheap rules?** Full-balance-send signature,
   balance accounting, and the existing "amount > 200,000 in a TRANSFER" rule.
5. **Where should manual review / model investment go?** High-signal segments.

All of these are answered with SQL against a real database — not in-memory
pandas — which is the hard-skill requirement this project targets.

---

## 3. Dataset

**Source:** PaySim — "Synthetic Financial Datasets For Fraud Detection"
(López-Rojas, Elmir, & Axelsson, 2017). The simulation is calibrated on real
mobile-money transaction logs and is one of the most widely used public fraud
datasets.

| Attribute | Description |
|---|---|
| `step` | Time unit: one step = one hour of simulation (30-day window, 1–744) |
| `type` | `CASH_IN`, `CASH_OUT`, `DEBIT`, `PAYMENT`, `TRANSFER` |
| `amount` | Transaction amount |
| `nameOrig` / `nameDest` | Originator / beneficiary account ID |
| `oldbalanceOrg` / `newbalanceOrig` | Originator balance before / after |
| `oldbalanceDest` / `newbalanceDest` | Beneficiary balance before / after |
| `isFraud` | Ground-truth label (1 = fraudulent) |
| `isFlaggedFraud` | Legacy rule flag (amount > 200,000 in a TRANSFER) |

**Data volume:** 6,362,620 transactions | **Fraud rows:** 8,213 (≈0.13%).

*Raw file stored at `data/raw/paysim_transactions.csv` (493 MB).*

---

## 4. Architecture

```
Raw PaySim log (CSV, 493 MB)
        │
        ▼
[1] ETL preparation  scripts/02a_prepare_data.py
        │  add type_id, amount_bucket, balance flags
        ▼
Clean fact CSV  data/processed/fact_transaction_clean.csv
        │
        ▼
[2] Warehouse load  scripts/02b_load_mysql.py
        │  MySQL 8 DDL (01_create_schema.sql) + bulk LOAD DATA
        ▼
MySQL database  fraudpulse_bi
  ├── dim_transaction_type   (5 channels + risk level)
  ├── dim_time_step          (step → hour / day / peak flag)
  ├── fact_transaction       (6.36M rows, 9 indexes)
  └── v_* business views     (7 reusable KPI views)
        │
        ├──► [3] SQL analytics  scripts/04_run_analytics.py
        │         └── output/tables/*.csv (19 files) · output/figures/*.png
        │             └── output/report_snapshot.html (static report)
        │
        └──► [4] BI dashboard   dashboard/app.py (Streamlit + Plotly)
```

**Why a star schema?** Separating the 5-type channel dimension and the
744-step time dimension from the 6.36M-row fact table keeps aggregations fast
(composite indexes on `(type_id, is_fraud)` and `(step, is_fraud)`), keeps
"risk level" business metadata in one place, and matches how a real
risk-analytics warehouse is modeled.

---

## 5. SQL Methodology & KPI Definitions (business definitions)

Every KPI used in this project is defined once and reused by views + the
query pack, so numbers never disagree.

| KPI | Definition (business definition) |
|---|---|
| Fraud rate (count) | `fraudulent txns / all txns × 100` |
| Fraud amount rate | `fraud amount / total amount × 100` |
| Detection coverage | `flagged fraud / actual fraud × 100` |
| Fraud share by channel | `channel fraud / total fraud × 100` |
| Full-balance-send flag | `oldbalance_org = amount` (sender drains the account) |

**SQL techniques demonstrated:** DDL with indexes & foreign key, recursive CTE
(to populate the time dimension), CTE + window functions (`ROW_NUMBER`,
`PERCENT_RANK`, `SUM() OVER ()`), `HAVING` filtering, business views, and 19
documented analytical queries.

---

## 6. Key Findings

> Numbers below are produced by running `sql/analytics_queries.sql` against the
> live MySQL warehouse (see `output/tables/*.csv`).

### 6.1 Portfolio-level
- **Total transactions:** 6,362,620
- **Total value:** 1,144,392,944,759.77
- **Fraud transactions:** 8,213 (fraud rate **0.129%**)
- **Fraud amount:** 12,056,415,427.84 (**1.05%** of total value)
- **Legacy rule detection coverage:** only **0.19%** — the existing
  "amount > 200,000 in a TRANSFER" rule flagged just **16** of 8,213 frauds.
  It is effectively blind.

### 6.2 Fraud is concentrated in two channels
**TRANSFER** and **CASH_OUT** carry **100%** of fraud, despite TRANSFER being
only **8.38%** of volume. Channel fraud rates:
- `TRANSFER` → **0.769%** (4,097 fraud, 49.88% of all fraud)
- `CASH_OUT` → **0.184%** (4,116 fraud, 50.12% of all fraud)
- `PAYMENT` / `DEBIT` / `CASH_IN` → **0 fraud**

TRANSFER is the highest-intensity channel (0.769% rate on a small volume
share) — the clearest risk segmentation for a control team.

### 6.3 Value targeting
Fraudulent transactions are on average **8.2×** larger than legitimate ones
(avg **1,467,967** vs **178,197**; median **441,423** vs **74,685**). The
**Huge (>100k)** band holds 6,506 of 8,213 frauds (~79%) with an average fraud
value of **1.84M**. The top 1% of fraudulent transactions alone account for
**23.8%** of fraud value.

### 6.4 Time pattern: fraud sleeps by day, strikes at night
Fraud rate by hour of day explodes in off-peak night hours:
- Hour 04 → **22.3%** · Hour 03 → **22.1%** · Hour 02 → **16.2%**
- Peak-business hours drop below **0.1%**
- Bucket view: **Night (off-peak) = 4.62%** vs **Afternoon (peak) = 0.075%**

This is a natural input for time-aware controls and staffing of manual review.

### 6.5 Headline cheap rule: full-balance send is 100% fraud
When the sender's starting balance exactly equals the amount sent
(`oldbalance_org = amount` → the account is drained to zero):

| Rule fired | Transactions | Fraud | Fraud rate | Fraud value |
|---|---|---|---|---|
| `full_balance_send = 1` | 8,034 | 8,034 | **100.00%** | 10,577,883,640.01 |
| `full_balance_send = 0` | 6,354,586 | 179 | 0.003% | 1,478,531,787.83 |

One SQL expression → **100% precision, 97.8% recall of all fraud**. By channel:
CASH_OUT full-send = 4,091 fraud (100%), TRANSFER full-send = 3,943 fraud (100%).
The remaining 179 frauds sit in non-full-send TRANSFER/CASH_OUT.

### 6.6 Note on a naive feature
A generic "balance-accounting mismatch" flag (`newbalance_orig ≠ old − amount`)
did **not** discriminate fraud (the clean-accounting group had the higher
fraud rate, 0.233% vs 0.001–0.008%). The lesson is that the **right business feature** (full-balance drain) matters more than
the plausible-looking one (generic mismatch). The data also shows fraud comes
from **positive-balance** originators (0.192% vs 0.002% for zero-balance).

### 6.7 Actors: single-shot fraudsters
Each of the 8,213 fraudulent customers was used for **exactly one** fraud
event (no repeat offenders inside this 30-day window). Fraud funds flow into a
small set of beneficiary accounts (top destinations receive ~10M each), which
points to **network/linkage analytics** as the next control layer.

---

## 7. Deep-Dive: turning the finding into a control rule

The full-balance-send rule is trivially implementable as a real-time check:

```sql
-- Real-time rule: block / review any transfer where the sender's balance
-- exactly equals the amount (account drained in a single move).
SELECT transaction_id, type_id, amount, name_orig
FROM fact_transaction
WHERE oldbalance_org = amount
  AND type_id IN (2, 3);          -- TRANSFER, CASH_OUT
```

**Impact estimate:** blocking these transactions would stop **97.8%** of fraud
events and **87.7%** of fraud value (10.58B / 12.06B) at ~8,034 alerts over
the 30-day window (~268 alerts/day) — an extremely favourable cost/benefit for
a manual-review queue, and a natural feature for a downstream ML model.

---

## 8. Deliverables & How to Reproduce

| Deliverable | Path |
|---|---|
| Interactive BI dashboard | `dashboard/app.py` (run `streamlit run dashboard/app.py`) |
| Static HTML report | `output/report_snapshot.html` |
| Query result audit trail | `output/tables/*.csv` (19 files) |
| Charts | `output/figures/*.png` |
| Full report (this doc) | `reports/FraudPulse_BI_Project_Report.md` |

**Reproduce:**
```bash
pip install -r requirements.txt
copy config\db_config.example.json config\db_config.json   # set MySQL password
python scripts/02a_prepare_data.py
python scripts/02b_load_mysql.py
python scripts/03_create_views.sql     # via your MySQL client, or run views script
python scripts/04_run_analytics.py
streamlit run dashboard/app.py
```

> **Performance note:** on machines where the InnoDB buffer pool is small
> (default 128 MB), bulk index creation on 6M+ rows is slow. This project
> loads data first (fast) and creates the 9 secondary indexes afterwards
> (`ALTER TABLE ... ADD INDEX`), which can be run once as a background step:
> `mysql> ALTER TABLE fact_transaction ADD INDEX idx_step (step), ...` (see
> `scripts/02b_load_mysql.py` for the full statement). The analytics and
> dashboard run correctly on the unindexed table too (full scans).

---

## 9. Limitations & Future Work

- **Synthetic data:** PaySim is a calibrated simulator, not a real production
  log; absolute numbers are indicative, not ground truth.
- **No merchant/device dimension:** no card/merchant/IP attributes exist; a
  production build would enrich the fact table.
- **Single-shot fraudsters:** with no repeat offenders in-window, entity
  linkage (same beneficiary, same device) is the next natural feature set.
- **Future:** add a scoring model tier (full-balance-send + amount + hour
  features → LightGBM), scheduled refresh (Airflow/cron), and KPI alerting.

---

*FraudPulse BI — built to demonstrate production-grade SQL + BI risk analytics.*

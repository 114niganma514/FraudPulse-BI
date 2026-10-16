# FraudPulse BI

**SQL Data Warehouse & BI Dashboard for Mobile Payment Fraud Analytics**

A complete, resume-ready risk-analytics project that demonstrates **SQL hard
skills on a real database (MySQL 8)** plus an **interactive BI dashboard**.
It is built on the public **PaySim** mobile-payment fraud dataset (6.36M
transactions) and runs the full pipeline end-to-end: raw data → dimensional
warehouse → business SQL analytics → interactive & static reporting.

---

## Why this project

| Skill highlighted | What you will show in an interview |
|---|---|
| **SQL (hard skills)** | Star-schema DDL, indexes, CTEs, window functions, views, aggregate analytics, KPI definitions (business definitions) |
| **Real database** | MySQL 8 server, JDBC-style Python connectors, bulk ETL load |
| **BI / reporting** | Interactive Streamlit + Plotly dashboard; static HTML report; CSV audit trail |
| **Business sense** | Fraud KPIs, risk segmentation, channel analysis, data-quality anomaly detection |

## Tech stack

- **Database**: MySQL 8.0 (`fraudpulse_bi`)
- **ETL**: Python 3 + pandas + PyMySQL + SQLAlchemy
- **BI**: Streamlit + Plotly
- **Reporting**: static HTML snapshot + CSV exports + figures

## Repository layout

```
FraudPulse_BI/
├── README.md
├── requirements.txt
├── config/
│   ├── db_config.example.json     # DB connection template
│   └── db_config.json             # YOUR local credentials (git-ignored)
├── data/
│   ├── raw/paysim_transactions.csv          # raw PaySim log (downloaded)
│   └── processed/fact_transaction_clean.csv # ETL-prepared fact CSV
├── scripts/
│   ├── 01_create_schema.sql       # DDL: database, dims, fact, indexes
│   ├── 02a_prepare_data.py        # derive business columns from raw log
│   ├── 02b_load_mysql.py          # run DDL + bulk-load fact table
│   ├── 03_create_views.sql        # reusable business views (business definitions)
│   ├── 04_run_analytics.py        # execute query pack → CSV/figures/HTML
│   ├── swap_database.py           # promote a staging schema to the final name
│   └── db_utils.py                # shared DB connection helpers
├── sql/
│   └── analytics_queries.sql      # 15 business SQL queries (documented)
├── dashboard/
│   └── app.py                     # Streamlit BI dashboard
├── reports/
│   └── FraudPulse_BI_Project_Report.md   # full English project report
└── output/
    ├── tables/*.csv               # query result audit trail
    ├── figures/*.png              # key charts
    └── report_snapshot.html       # static HTML report
```

## How to run

### 0. Prerequisites
- MySQL 8 server running locally
- Python 3.10+
- PaySim CSV from Kaggle (`ealaxi/paysim1`), saved as `data/raw/paysim_transactions.csv` (not committed, ~470MB)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure the database connection
```bash
copy config\db_config.example.json config\db_config.json
# edit config/db_config.json with your MySQL host/port/user/password
```

### 3. Run the ETL pipeline
```bash
python scripts/02a_prepare_data.py   # raw CSV -> clean fact CSV (≈2-4 min)
python scripts/02b_load_mysql.py     # create schema + bulk load (≈3-5 min)
```

### 4. Run the analytics query pack
```bash
python scripts/04_run_analytics.py   # outputs CSV tables + figures + HTML report
```
Open `output/report_snapshot.html` in a browser for the static report.

### 5. Launch the interactive BI dashboard
```bash
streamlit run dashboard/app.py
```
Open the URL printed in the terminal (default http://localhost:8501).

> **Headline finding** (computed on this warehouse): when a sender's balance
> equals the exact amount sent (`oldbalance_org = amount`), the transaction is
> fraudulent in **100%** of cases — one SQL rule captures **97.8%** of all
> fraud. Full results in `output/report_snapshot.html` and the project report.

## Schema overview (star model)

- **`dim_transaction_type`** — 5 mobile-money channels with risk-level tags
- **`dim_time_step`** — step → hour-of-day / day / peak-hour attributes
- **`fact_transaction`** — 6.36M transactions with balance columns and
  derived flags (`orig_balance_inconsistent`, `dest_balance_inconsistent`,
  `amount_bucket`)
- **Business views** — `v_fraud_summary`, `v_fraud_by_type`, `v_fraud_by_hour`,
  `v_fraud_by_day`, `v_fraud_by_amount_bucket`, `v_balance_inconsistency`,
  `v_top_risk_customers`

## Key business findings (summary)

*(Full numbers in `reports/FraudPulse_BI_Project_Report.md`.)*

- Fraud is concentrated in **TRANSFER** and **CASH_OUT** channels.
- Fraudulent transactions are typically **larger** than legitimate ones.
- **Balance-inconsistency** flags strongly correlate with fraud → cheap rule feature.
- The legacy flagging rule (amount > 200k in a TRANSFER) captures only a
  **small fraction** of actual fraud.
- Fraud count is heavily right-skewed per customer → repeat-offender analytics.

## Data source

PaySim (mobile money simulator) — *"Synthetic Financial Datasets For Fraud
Detection"*, López-Rojas et al., 2017. Public dataset widely used for fraud
detection research.

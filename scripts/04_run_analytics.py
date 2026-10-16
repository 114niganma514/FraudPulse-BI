"""
04_run_analytics.py - Execute the analytics query pack against MySQL and
generate the static reporting deliverables.

Outputs produced:
  * output/tables/<query_name>.csv     - raw result sets (audit trail)
  * output/figures/*.png               - key charts
  * output/report_snapshot.html        - self-contained static HTML report

The same queries power the interactive Streamlit dashboard, so the numbers
in the static report and the live dashboard always agree.

Usage:
    python scripts/04_run_analytics.py
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from db_utils import get_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUERIES_SQL = PROJECT_ROOT / "sql" / "analytics_queries.sql"
OUT_TABLES = PROJECT_ROOT / "output" / "tables"
OUT_FIGURES = PROJECT_ROOT / "output" / "figures"
OUT_HTML = PROJECT_ROOT / "output" / "report_snapshot.html"

plt.rcParams.update({"figure.facecolor": "white", "axes.grid": True,
                     "grid.alpha": 0.35, "font.size": 9})


def parse_query_pack(sql_text: str) -> list[tuple[str, str]]:
    """Split the SQL file on '-- @query <name>' headers.

    Each block looks like:
        -- @query <name>
        -- business comments ...
        -- ========...=======
        <SQL statement>;
        -- ========...=======
    The actual SQL is the part between the first and last '====' divider.
    """
    blocks = re.split(r"--\s*@query\s+(\w+)", sql_text)
    queries: list[tuple[str, str]] = []
    # blocks[0] is the preamble before the first marker
    for i in range(1, len(blocks), 2):
        name = blocks[i].strip()
        chunk = blocks[i + 1]
        parts = re.split(r"--\s*=+", chunk)
        if len(parts) >= 2:
            body = parts[1].strip()
        else:
            body = chunk.strip()
        if body:
            queries.append((name, body))
    return queries


def clean_string_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Strip stray CR/LF from string columns (defensive against Windows
    line-ending artifacts from the bulk load)."""
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].astype(str).str.strip().str.replace("\r", "").str.replace("\n", " ")
    return df


def run_all(engine) -> dict[str, pd.DataFrame]:
    results: dict[str, pd.DataFrame] = {}
    sql_text = QUERIES_SQL.read_text(encoding="utf-8")
    for name, stmt in parse_query_pack(sql_text):
        df = pd.read_sql(stmt, engine)
        df = clean_string_cells(df)
        results[name] = df
        df.to_csv(OUT_TABLES / f"{name}.csv", index=False)
        print(f"  - {name:<26} rows={len(df):>6}")
    return results


def chart_fraud_by_type(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(7, 4))
    df = df.sort_values("fraud_count", ascending=True)
    ax.barh(df["type_name"], df["fraud_count"], color="#d64541")
    for i, (v, pct) in enumerate(zip(df["fraud_count"], df["fraud_rate_pct"])):
        ax.text(v, i, f"  {v:,}  ({pct:.2f}%)", va="center", fontsize=8)
    ax.set_title("Fraud count by transaction type (fraud rate %)")
    ax.set_xlabel("Fraudulent transactions")
    return _save_fig(fig, "fraud_by_type.png")


def chart_fraud_by_hour(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(df["hour_of_day"], df["fraud_count"], marker="o", ms=4, color="#22313f")
    ax.set_title("Fraudulent transactions by hour of day")
    ax.set_xlabel("Hour of day (0-23)")
    ax.set_ylabel("Fraud count")
    ax.set_xticks(range(0, 24, 2))
    return _save_fig(fig, "fraud_by_hour.png")


def chart_fraud_by_day(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.plot(df["day_of_month"], df["fraud_count"], marker="o", ms=3, color="#1e824c")
    ax.set_title("Fraudulent transactions by day (30-day window)")
    ax.set_xlabel("Day of simulation")
    ax.set_ylabel("Fraud count")
    return _save_fig(fig, "fraud_by_day.png")


def chart_amount_bucket(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(7, 4))
    df = df.sort_values("transaction_count", ascending=True)
    ax.barh(df["amount_bucket"], df["transaction_count"], color="#f39c12", label="All txns")
    ax.barh(df["amount_bucket"], df["fraud_count"], color="#c0392b", label="Fraud txns")
    ax.set_xscale("log")
    ax.set_title("Transactions by amount band (log scale)")
    ax.legend()
    return _save_fig(fig, "amount_bucket.png")


def _save_fig(fig, name: str) -> str:
    path = OUT_FIGURES / name
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return str(path)


def img_to_b64(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def build_html(results: dict[str, pd.DataFrame], charts: dict[str, str]) -> None:
    kpi = results["q01_portfolio_kpis"].iloc[0]

    def chart_block(name: str, title: str) -> str:
        if name not in charts:
            return ""
        return (
            f'<div class="card"><h3>{title}</h3>'
            f'<img src="data:image/png;base64,{img_to_b64(charts[name])}" '
            f'style="width:100%;border-radius:6px;"/></div>'
        )

    def table_block(name: str, title: str, max_rows: int = 10) -> str:
        if name not in results:
            return ""
        df = results[name].head(max_rows)
        thead = "".join(f"<th>{c}</th>" for c in df.columns)
        rows = ""
        for _, r in df.iterrows():
            tds = "".join(f"<td>{v:,}</td>" if isinstance(v, (int, float)) else f"<td>{v}</td>"
                          for v in r)
            rows += f"<tr>{tds}</tr>"
        return (
            f'<div class="card"><h3>{title}</h3>'
            f'<table><thead><tr>{thead}</tr></thead><tbody>{rows}</tbody></table></div>'
        )

    kpi_cards = f"""
    <div class="kpis">
      <div class="kpi"><div class="num">{kpi['total_transactions']:,}</div><div class="lbl">Total transactions</div></div>
      <div class="kpi"><div class="num">{kpi['total_amount']:,.0f}</div><div class="lbl">Total amount</div></div>
      <div class="kpi"><div class="num">{kpi['fraud_transactions']:,}</div><div class="lbl">Fraud transactions</div></div>
      <div class="kpi"><div class="num">{kpi['fraud_rate_pct']:.3f}%</div><div class="lbl">Fraud rate</div></div>
      <div class="kpi"><div class="num">{kpi['detection_coverage_pct']:.2f}%</div><div class="lbl">Legacy rule coverage</div></div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>FraudPulse BI - Analytics Report Snapshot</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 24px; background: #f5f6fa; color: #2c3e50; }}
  h1 {{ color: #1e3799; }} h2 {{ color: #0c2461; border-bottom: 2px solid #eee; padding-bottom: 4px; }}
  .kpis {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0; }}
  .kpi {{ background: #fff; border-radius: 10px; padding: 14px 22px; box-shadow: 0 1px 4px rgba(0,0,0,.08); min-width: 150px; }}
  .kpi .num {{ font-size: 26px; font-weight: 700; color: #1e3799; }}
  .kpi .lbl {{ font-size: 12px; color: #7f8c8d; margin-top: 4px; }}
  .card {{ background: #fff; border-radius: 10px; padding: 16px; margin: 16px 0; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  th, td {{ border: 1px solid #e3e6ec; padding: 6px 8px; text-align: right; }}
  th {{ background: #1e3799; color: #fff; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .grid .card {{ margin: 0; }}
  footer {{ margin-top: 30px; color: #95a5a6; font-size: 12px; }}
</style></head><body>
<h1>FraudPulse BI - Analytics Report Snapshot</h1>
<p>Static export generated by <code>scripts/04_run_analytics.py</code>.
Data source: MySQL <code>fraudpulse_bi</code> (PaySim mobile-payment log).</p>
{kpi_cards}
<h2>1. Portfolio KPIs</h2>
{table_block("q01_portfolio_kpis", "Key metrics", 3)}
<h2>2. Fraud concentration</h2>
<div class="grid">
  {chart_block("fraud_by_type", "Fraud by transaction type")}
  {chart_block("amount_bucket", "Transactions by amount band")}
</div>
<table_block_placeholder>
<h2>3. Fraud patterns over time</h2>
<div class="grid">
  {chart_block("fraud_by_hour", "Fraud by hour of day")}
  {chart_block("fraud_by_day", "Fraud by day")}
</div>
<h2>4. Channel & amount details</h2>
{table_block("q02_fraud_by_type", "Fraud by transaction type (detail)", 10)}
{table_block("q05_fraud_by_amount_bucket", "Fraud by amount band", 10)}
<h2>5. Data quality & rules</h2>
{table_block("q07_balance_inconsistency", "Balance inconsistency vs fraud", 10)}
{table_block("q08_flagged_vs_actual_fraud", "Legacy rule vs actual fraud", 10)}
<h2>6. Customer risk</h2>
{table_block("q09_top_risk_customers", "Top risky originator accounts", 10)}
{table_block("q10_top_fraud_destinations", "Top fraud destinations", 10)}
<footer>FraudPulse BI &mdash; SQL Data Warehouse &amp; BI Dashboard on MySQL (PaySim dataset).</footer>
</body></html>"""
    # Replace placeholder (kept simple to avoid f-string brace escaping)
    html = html.replace("<table_block_placeholder>", "")
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"HTML report written: {OUT_HTML}")


def main() -> None:
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    OUT_FIGURES.mkdir(parents=True, exist_ok=True)

    engine = get_engine()
    print("Executing analytics query pack ...")
    results = run_all(engine)

    print("Generating charts ...")
    charts = {}
    charts["fraud_by_type"] = chart_fraud_by_type(results["q02_fraud_by_type"])
    charts["fraud_by_hour"] = chart_fraud_by_hour(results["q03_fraud_by_hour"])
    charts["fraud_by_day"] = chart_fraud_by_day(results["q04_fraud_by_day"])
    charts["amount_bucket"] = chart_amount_bucket(results["q05_fraud_by_amount_bucket"])

    print("Building static HTML report ...")
    build_html(results, charts)

    print("Done. Tables:", len(results), "| Figures:", len(charts))


if __name__ == "__main__":
    main()

"""
FraudPulse BI - Interactive Dashboard (Streamlit + Plotly)

A self-service BI dashboard on top of the MySQL `fraudpulse_bi` warehouse.
Every chart is produced by running SQL against the live database, so the
dashboard always reflects the current state of the data.

Run:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from db_utils import get_engine, load_db_config  # noqa: E402

st.set_page_config(
    page_title="FraudPulse BI",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------------
# Branding & data loading helpers
# ----------------------------------------------------------------------------
FRAUD_COLOR = "#d64541"
LEGIT_COLOR = "#2d9cdb"
ACCENT = "#1e3799"


@st.cache_resource
def init_engine():
    cfg = load_db_config()
    return get_engine(cfg)


@st.cache_data(ttl=300, show_spinner=False)
def query(sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, init_engine())


def kpi_row(metrics: list[tuple[str, str]]):
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)


st.sidebar.markdown(
    "<h2 style='text-align:center;color:#1e3799;'>🛡️ FraudPulse BI</h2>"
    "<p style='text-align:center;color:#7f8c8d;'>SQL Data Warehouse & BI Dashboard<br/>"
    "Mobile Payment Fraud Analytics · MySQL + PaySim</p>",
    unsafe_allow_html=True,
)

# ---- Sidebar: connection status + global filters ---------------------------
try:
    cfg = load_db_config()
    st.sidebar.success(f"Connected · {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}")
    engine_ok = True
except Exception as exc:  # noqa: BLE001
    engine_ok = False
    st.sidebar.error(f"DB config missing/invalid: {exc}")
    st.sidebar.info("Copy config/db_config.example.json → config/db_config.json and set your MySQL password.")
    st.stop()

if engine_ok:
    try:
        init_engine()
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"Connection failed: {exc}")
        st.stop()

# Global filter panel
st.sidebar.markdown("### Filters")
types_df = query("SELECT type_name FROM dim_transaction_type ORDER BY type_id")
selected_types = st.sidebar.multiselect(
    "Transaction types", options=types_df["type_name"].tolist(),
    default=types_df["type_name"].tolist(),
)

day_range = st.sidebar.slider("Simulation day (1-31)", 1, 31, (1, 31))
amount_max = st.sidebar.number_input("Max amount (filter)", min_value=1, value=5_000_000, step=100_000)

only_fraud = st.sidebar.checkbox("Fraud transactions only", value=False)

FILTER_SQL = "1=1"
if selected_types:
    in_list = ",".join(f"'{t}'" for t in selected_types)
    FILTER_SQL += f" AND t.type_name IN ({in_list})"
FILTER_SQL += f" AND d.day_of_month BETWEEN {day_range[0]} AND {day_range[1]}"
FILTER_SQL += f" AND f.amount <= {amount_max}"
if only_fraud:
    FILTER_SQL += " AND f.is_fraud = 1"

FACT_FROM = (
    "FROM fact_transaction f "
    "JOIN dim_transaction_type t ON f.type_id = t.type_id "
    "JOIN dim_time_step d ON f.step = d.step"
)

# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------
tab_overview, tab_fraud, tab_customer, tab_rules, tab_sql = st.tabs(
    ["📊 Overview", "🎯 Fraud Analysis", "👤 Customer Risk", "⚖️ Rules & Data Quality", "🗄️ SQL Lab"]
)

# ============================ OVERVIEW ======================================
with tab_overview:
    st.subheader("Portfolio Overview")

    kpi_df = query(
        f"SELECT COUNT(*) AS total_txns, SUM(f.amount) AS total_amount, "
        f"SUM(f.is_fraud) AS fraud_txns, SUM(f.is_fraud*f.amount) AS fraud_amount "
        f"{FACT_FROM} WHERE {FILTER_SQL}"
    ).iloc[0]

    fraud_rate = kpi_df["fraud_txns"] / kpi_df["total_txns"] * 100 if kpi_df["total_txns"] else 0.0
    kpi_row([
        ("Transactions", f"{kpi_df['total_txns']:,}"),
        ("Total amount", f"{kpi_df['total_amount']:,.0f}"),
        ("Fraud transactions", f"{kpi_df['fraud_txns']:,}"),
        ("Fraud amount", f"{kpi_df['fraud_amount']:,.0f}"),
        ("Fraud rate", f"{fraud_rate:.3f}%"),
    ])

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**Transaction mix by type**")
        mix = query(
            f"SELECT t.type_name AS type, COUNT(*) AS cnt, SUM(f.amount) AS amt "
            f"{FACT_FROM} WHERE {FILTER_SQL} GROUP BY t.type_name ORDER BY cnt DESC"
        )
        fig = px.pie(mix, names="type", values="cnt", hole=0.45,
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_traces(textinfo="label+percent")
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown("**Daily transaction volume & fraud (30-day trend)**")
        daily = query(
            f"SELECT d.day_of_month AS day, COUNT(*) AS txns, SUM(f.is_fraud) AS fraud "
            f"{FACT_FROM} WHERE {FILTER_SQL} GROUP BY d.day_of_month ORDER BY day"
        )
        fig = go.Figure()
        fig.add_bar(x=daily["day"], y=daily["txns"], name="All txns",
                    marker_color=LEGIT_COLOR, opacity=0.7)
        fig.add_bar(x=daily["day"], y=daily["fraud"], name="Fraud txns",
                    marker_color=FRAUD_COLOR)
        fig.update_layout(barmode="overlay", xaxis_title="Day of simulation")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Total value transacted by day**")
    value_daily = query(
        f"SELECT d.day_of_month AS day, SUM(f.amount) AS amt "
        f"{FACT_FROM} WHERE {FILTER_SQL} GROUP BY d.day_of_month ORDER BY day"
    )
    fig = px.area(value_daily, x="day", y="amt", color_discrete_sequence=[ACCENT])
    fig.update_layout(xaxis_title="Day of simulation", yaxis_title="Amount")
    st.plotly_chart(fig, use_container_width=True)

# ============================ FRAUD ANALYSIS ================================
with tab_fraud:
    st.subheader("Fraud Analysis")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**Fraud count & rate by transaction type**")
        by_type = query(
            f"SELECT t.type_name AS type, COUNT(*) AS txns, SUM(f.is_fraud) AS fraud, "
            f"ROUND(SUM(f.is_fraud)/COUNT(*)*100,3) AS rate "
            f"{FACT_FROM} WHERE {FILTER_SQL} GROUP BY t.type_name ORDER BY fraud DESC"
        )
        fig = px.bar(by_type, x="type", y="fraud", color="type",
                     text="rate", color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_traces(texttemplate="%{text:.2f}%", textposition="outside")
        fig.update_layout(xaxis_title="", yaxis_title="Fraud transactions",
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown("**Fraud rate by hour of day**")
        by_hour = query(
            f"SELECT d.hour_of_day AS hour, COUNT(*) AS txns, SUM(f.is_fraud) AS fraud, "
            f"ROUND(SUM(f.is_fraud)/COUNT(*)*100,3) AS rate "
            f"{FACT_FROM} WHERE {FILTER_SQL} GROUP BY d.hour_of_day ORDER BY hour"
        )
        fig = go.Figure()
        fig.add_bar(x=by_hour["hour"], y=by_hour["fraud"], name="Fraud count",
                    marker_color=FRAUD_COLOR)
        fig.add_scatter(x=by_hour["hour"], y=by_hour["rate"], name="Fraud rate %",
                        yaxis="y2", line=dict(color=ACCENT, width=2))
        fig.update_layout(yaxis_title="Fraud count",
                          yaxis2=dict(title="Fraud rate %", overlaying="y", side="right"),
                          xaxis_title="Hour of day")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Fraud by amount band (log scale)**")
    by_bucket = query(
        f"SELECT f.amount_bucket AS bucket, COUNT(*) AS txns, SUM(f.is_fraud) AS fraud, "
        f"ROUND(SUM(f.is_fraud)/COUNT(*)*100,3) AS rate, MIN(f.amount) AS min_amt "
        f"{FACT_FROM} WHERE {FILTER_SQL} GROUP BY f.amount_bucket ORDER BY min_amt"
    )
    by_bucket["bucket"] = (by_bucket["bucket"].astype(str)
                           .str.replace("\r", "").str.replace("\n", " ").str.strip())
    fig = go.Figure()
    fig.add_bar(x=by_bucket["bucket"], y=by_bucket["txns"], name="All txns",
                marker_color=LEGIT_COLOR)
    fig.add_bar(x=by_bucket["bucket"], y=by_bucket["fraud"], name="Fraud txns",
                marker_color=FRAUD_COLOR)
    fig.update_layout(barmode="group", xaxis_title="Amount band",
                      yaxis_title="Transactions", yaxis_type="log")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Average transaction value: fraud vs legitimate**")
    avg_df = query(
        f"SELECT f.is_fraud AS is_fraud, COUNT(*) AS txns, ROUND(AVG(f.amount),2) AS avg_amt "
        f"{FACT_FROM} WHERE {FILTER_SQL} GROUP BY f.is_fraud"
    )
    avg_df["label"] = avg_df["is_fraud"].map({0: "Legitimate", 1: "Fraud"})
    fig = px.bar(avg_df, x="label", y="avg_amt", color="label",
                 color_discrete_map={"Legitimate": LEGIT_COLOR, "Fraud": FRAUD_COLOR},
                 text_auto=".2s")
    fig.update_layout(xaxis_title="", yaxis_title="Average amount", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

# ============================ CUSTOMER RISK =================================
with tab_customer:
    st.subheader("Customer Risk")

    st.markdown("**Top 20 risky originator accounts (by fraud count)**")
    top_orig = query(
        f"SELECT f.name_orig AS customer, COUNT(*) AS txns, SUM(f.is_fraud) AS fraud, "
        f"ROUND(SUM(f.is_fraud)/COUNT(*)*100,2) AS rate, ROUND(SUM(f.is_fraud*f.amount),0) AS fraud_amt "
        f"{FACT_FROM} WHERE {FILTER_SQL} GROUP BY f.name_orig "
        f"HAVING fraud > 0 ORDER BY fraud DESC, fraud_amt DESC LIMIT 20"
    )
    fig = px.bar(top_orig.sort_values("fraud"), x="fraud", y="customer",
                 orientation="h", color="fraud", color_continuous_scale="Reds",
                 text="rate")
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(xaxis_title="Fraud transactions", yaxis_title="",
                      showlegend=False, height=520)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Top fraud destinations (where funds flow)**")
    top_dest = query(
        f"SELECT f.name_dest AS destination, COUNT(*) AS fraud_txns, "
        f"ROUND(SUM(f.amount),0) AS fraud_amt "
        f"{FACT_FROM} WHERE {FILTER_SQL} AND f.is_fraud=1 "
        f"GROUP BY f.name_dest ORDER BY fraud_amt DESC LIMIT 20"
    )
    fig = px.bar(top_dest.sort_values("fraud_amt"), x="fraud_amt", y="destination",
                 orientation="h", color="fraud_amt", color_continuous_scale="Blues")
    fig.update_layout(xaxis_title="Fraud amount received", yaxis_title="",
                      showlegend=False, height=520)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Behavioral fingerprint: fraud count per customer**")
    dist = query(
        "WITH per_customer AS ("
        f" SELECT f.name_orig, SUM(f.is_fraud) AS fraud, COUNT(*) AS total "
        f" {FACT_FROM} WHERE {FILTER_SQL} GROUP BY f.name_orig) "
        "SELECT fraud AS fraud_txns, COUNT(*) AS customers FROM per_customer "
        "GROUP BY fraud ORDER BY fraud"
    )
    fig = px.bar(dist, x="fraud_txns", y="customers", log_y=True,
                 color="customers", color_continuous_scale="Greens")
    fig.update_layout(xaxis_title="Fraudulent transactions per customer",
                      yaxis_title="Customers (log)", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Behavioral fingerprint: in this dataset each fraudulent customer is used "
        "for exactly one fraud event (single-shot accounts), so entity-level "
        "linkage/network features matter as much as repeat-offender history."
    )

# ============================ RULES & DATA QUALITY ==========================
with tab_rules:
    st.subheader("Rules & Data Quality")

    st.markdown("**Headline rule: full-balance send (oldbalance_org = amount)**")
    full = query(
        f"SELECT (f.oldbalance_org = f.amount) AS full_send, COUNT(*) AS txns, "
        f"SUM(f.is_fraud) AS fraud, ROUND(SUM(f.is_fraud)/COUNT(*)*100,2) AS rate "
        f"{FACT_FROM} WHERE {FILTER_SQL} GROUP BY full_send ORDER BY full_send DESC"
    )
    full["label"] = full["full_send"].map({1: "full balance sent", 0: "partial / other"})
    fig = px.bar(full, x="label", y="txns", color="label", log_y=True,
                 color_discrete_map={"full balance sent": FRAUD_COLOR,
                                     "partial / other": LEGIT_COLOR},
                 text="rate")
    fig.update_traces(texttemplate="fraud rate %{text}%", textposition="outside")
    fig.update_layout(xaxis_title="Sender balance vs amount", yaxis_title="Transactions (log)",
                      showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "When the sender's account balance exactly equals the transaction amount "
        "(the full balance is drained), the transaction is fraudulent in ~100% of "
        "cases in this dataset — a cheap, high-precision rule feature."
    )

    st.markdown("**Fraud by originator starting balance (money-creation signal)**")
    zb = query(
        f"SELECT CASE WHEN f.oldbalance_org = 0 THEN 'zero' ELSE 'positive' END AS state, "
        f"COUNT(*) AS txns, SUM(f.is_fraud) AS fraud, "
        f"ROUND(SUM(f.is_fraud)/COUNT(*)*100,3) AS rate "
        f"{FACT_FROM} WHERE {FILTER_SQL} "
        f"GROUP BY state ORDER BY fraud DESC"
    )
    zb["label"] = "orig balance = " + zb["state"]
    fig = px.bar(zb, x="label", y="rate", color="rate", color_continuous_scale="RdYlGn_r",
                 text="fraud")
    fig.update_traces(texttemplate="fraud=%{text}", textposition="outside")
    fig.update_layout(xaxis_title="Originator starting balance", yaxis_title="Fraud rate %",
                      showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Legacy rule vs actual fraud (detection coverage)**")
    flag = query(
        f"SELECT f.is_fraud AS is_fraud, f.is_flagged_fraud AS flagged, "
        f"COUNT(*) AS txns, ROUND(SUM(f.amount),0) AS amt "
        f"{FACT_FROM} WHERE {FILTER_SQL} "
        f"GROUP BY f.is_fraud, f.is_flagged_fraud ORDER BY is_fraud DESC, flagged DESC"
    )
    flag["label"] = ("fraud=" + flag["is_fraud"].astype(str) +
                     ", flagged=" + flag["flagged"].astype(str))
    fig = px.bar(flag, x="label", y="txns", color="label", log_y=True,
                 color_discrete_sequence=px.colors.qualitative.Set1, text="txns")
    fig.update_traces(texttemplate="%{text:,}", textposition="outside")
    fig.update_layout(xaxis_title="(is_fraud, is_flagged_fraud)", yaxis_title="Transactions (log)",
                      showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Fraud rate by time bucket (peak vs off-peak)**")
    tb = query(
        f"SELECT d.time_bucket AS bucket, d.is_peak_hour AS peak, COUNT(*) AS txns, "
        f"SUM(f.is_fraud) AS fraud, ROUND(SUM(f.is_fraud)/COUNT(*)*100,3) AS rate "
        f"{FACT_FROM} WHERE {FILTER_SQL} "
        f"GROUP BY d.time_bucket, d.is_peak_hour ORDER BY rate DESC"
    )
    tb["peak_label"] = tb["peak"].map({0: "off-peak", 1: "peak"})
    tb["label"] = tb["bucket"] + " (" + tb["peak_label"] + ")"
    fig = px.bar(tb, x="label", y="rate", color="rate", color_continuous_scale="Purples",
                 text="fraud")
    fig.update_traces(texttemplate="fraud=%{text}", textposition="outside")
    fig.update_layout(xaxis_title="Time bucket", yaxis_title="Fraud rate %",
                      showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

# ============================ SQL LAB =======================================
with tab_sql:
    st.subheader("SQL Lab — run ad-hoc SQL against the warehouse")

    st.info(
        "Write your own SQL against the `fraudpulse_bi` schema. "
        "Available tables: `fact_transaction`, `dim_transaction_type`, `dim_time_step`, "
        "and the business views `v_fraud_summary`, `v_fraud_by_type`, `v_fraud_by_hour`, "
        "`v_fraud_by_day`, `v_fraud_by_amount_bucket`, `v_balance_inconsistency`, "
        "`v_top_risk_customers`."
    )

    default_sql = (
        "SELECT t.type_name, COUNT(*) AS txns, SUM(f.is_fraud) AS fraud, "
        "ROUND(SUM(f.is_fraud)/COUNT(*)*100,3) AS fraud_rate_pct\n"
        "FROM fact_transaction f\n"
        "JOIN dim_transaction_type t USING (type_id)\n"
        "GROUP BY t.type_name\n"
        "ORDER BY fraud DESC;"
    )
    sql_input = st.text_area("SQL", value=default_sql, height=200, key="sql_lab")
    run_btn = st.button("Run query", type="primary", use_container_width=True)

    if run_btn and sql_input.strip():
        try:
            with st.spinner("Executing ..."):
                result = pd.read_sql(sql_input, init_engine())
            st.success(f"Query returned {len(result):,} row(s).")
            st.dataframe(result, use_container_width=True, height=420)
            st.download_button(
                "Download result (CSV)", result.to_csv(index=False),
                file_name="sql_lab_result.csv", mime="text/csv",
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Query failed: {exc}")

# ----------------------------------------------------------------------------
st.sidebar.caption("FraudPulse BI · MySQL 8 · PaySim dataset · SQL + BI")

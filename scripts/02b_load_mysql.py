"""
02b_load_mysql.py - Create the warehouse schema and bulk load the fact table.

Pipeline:
  1. Reads config/db_config.json
  2. Executes scripts/01_create_schema.sql  (drops & recreates schema)
  3. Bulk loads data/processed/fact_transaction_clean.csv into
     `fact_transaction` using chunked executemany inserts.

The load is wrapped in a single transaction per batch so a failure can be
rolled back without corrupting the table.

Usage:
    python scripts/02b_load_mysql.py
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd

from db_utils import get_connection, load_db_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = PROJECT_ROOT / "scripts" / "01_create_schema.sql"
CLEAN_CSV = PROJECT_ROOT / "data" / "processed" / "fact_transaction_clean.csv"

BATCH = 100_000  # rows per executemany batch

# Secondary indexes are added *after* the bulk load (see main): building them
# incrementally during LOAD DATA on 6M+ rows is far slower than one bulk ALTER.
DROP_SECONDARY_INDEXES = """
ALTER TABLE fact_transaction
    DROP FOREIGN KEY fk_fact_type,
    DROP INDEX idx_step,
    DROP INDEX idx_type,
    DROP INDEX idx_name_orig,
    DROP INDEX idx_name_dest,
    DROP INDEX idx_is_fraud,
    DROP INDEX idx_amount,
    DROP INDEX idx_type_fraud,
    DROP INDEX idx_step_fraud,
    DROP INDEX idx_orig_inc
"""

ADD_SECONDARY_INDEXES = """
ALTER TABLE fact_transaction
    ADD INDEX idx_step (step),
    ADD INDEX idx_type (type_id),
    ADD INDEX idx_name_orig (name_orig),
    ADD INDEX idx_name_dest (name_dest),
    ADD INDEX idx_is_fraud (is_fraud),
    ADD INDEX idx_amount (amount),
    ADD INDEX idx_type_fraud (type_id, is_fraud),
    ADD INDEX idx_step_fraud (step, is_fraud),
    ADD INDEX idx_orig_inc (orig_balance_inconsistent, is_fraud),
    ADD CONSTRAINT fk_fact_type FOREIGN KEY (type_id)
        REFERENCES dim_transaction_type (type_id)
"""

INSERT_SQL = """
INSERT INTO fact_transaction (
    step, type_id, amount, name_orig, oldbalance_org, newbalance_orig,
    name_dest, oldbalance_dest, newbalance_dest, is_fraud, is_flagged_fraud,
    orig_balance_inconsistent, dest_balance_inconsistent, amount_bucket
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
"""


def run_schema_sql(conn, db_name: str) -> None:
    """Execute the DDL script statement by statement.

    The canonical schema script targets ``fraudpulse_bi``; when loading into a
    different database (e.g. a staging database while the target is locked),
    the database identifier is substituted before execution.
    Comments are stripped *before* splitting on ';' so that semicolons inside
    comment text never break the statement boundaries.
    """
    sql_text = SCHEMA_SQL.read_text(encoding="utf-8")
    if db_name != "fraudpulse_bi":
        sql_text = sql_text.replace("fraudpulse_bi", db_name)
    # Strip -- line comments and /* */ block comments (no such markers exist
    # inside string literals in this DDL).
    sql_text = re.sub(r"--[^\n]*", "", sql_text)
    sql_text = re.sub(r"/\*.*?\*/", "", sql_text, flags=re.S)
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]

    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
    conn.commit()
    print(f"Schema created: {len(statements)} statements executed.")


def load_fact_table_fast(conn) -> None:
    """Bulk load the clean CSV with LOAD DATA LOCAL INFILE (fast path).

    The clean CSV column order matches the fact table column list (excluding
    the auto-increment PK), so the column list is explicit for safety.
    """
    if not CLEAN_CSV.exists():
        sys.exit(f"Clean CSV not found: {CLEAN_CSV}. Run 02a_prepare_data.py first.")

    csv_path = str(CLEAN_CSV).replace("\\", "/")
    sql = f"""
        LOAD DATA LOCAL INFILE '{csv_path}'
        INTO TABLE fact_transaction
        FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
        LINES TERMINATED BY '\\n'
        IGNORE 1 LINES
        (step, type_id, amount, name_orig, oldbalance_org, newbalance_orig,
         name_dest, oldbalance_dest, newbalance_dest, is_fraud, is_flagged_fraud,
         orig_balance_inconsistent, dest_balance_inconsistent, amount_bucket)
    """
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"Fact table load complete in {time.time() - t0:.1f}s (LOAD DATA)")


def load_fact_table_chunked(conn) -> None:
    """Fallback loader: stream the clean CSV into the fact table in batches.

    Kept for compatibility with servers where LOCAL INFILE is disabled.
    """
    if not CLEAN_CSV.exists():
        sys.exit(f"Clean CSV not found: {CLEAN_CSV}. Run 02a_prepare_data.py first.")

    reader = pd.read_csv(
        CLEAN_CSV,
        chunksize=BATCH,
        dtype={
            "name_orig": str,
            "name_dest": str,
            "amount_bucket": str,
        },
    )

    total = 0
    t0 = time.time()
    with conn.cursor() as cur:
        for i, chunk in enumerate(reader, start=1):
            rows = []
            for rec in chunk.itertuples(index=False, name=None):
                row = []
                for v in rec:
                    if v is None or pd.isna(v):
                        row.append(None)
                    elif hasattr(v, "item"):  # numpy scalars -> native types
                        row.append(v.item())
                    else:
                        row.append(v)
                rows.append(tuple(row))
            try:
                cur.executemany(INSERT_SQL, rows)
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                raise RuntimeError(f"Batch {i} failed: {exc}") from exc

            total += len(rows)
            elapsed = time.time() - t0
            print(
                f"batch {i}: {len(rows):,} rows inserted "
                f"(cumulative {total:,}, {elapsed:.1f}s)"
            )

    print(f"Fact table load complete: {total:,} rows in {time.time() - t0:.1f}s")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="FraudPulse BI warehouse ETL")
    parser.add_argument(
        "--database", default=None,
        help="Override the target database (e.g. a staging db while the "
             "final one is locked by a long-running rollback).",
    )
    args = parser.parse_args()

    cfg = load_db_config()
    if args.database:
        cfg["database"] = args.database

    conn = get_connection(cfg)
    try:
        # Enable the server-side LOCAL INFILE capability for bulk loading
        with conn.cursor() as cur:
            try:
                cur.execute("SET GLOBAL local_infile = 1")
            except Exception as exc:  # noqa: BLE001
                print(f"Note: could not SET GLOBAL local_infile ({exc}); "
                      "falling back to chunked inserts.")
        conn.commit()

        print(f"1) Running schema DDL (database={cfg['database']}) ...")
        run_schema_sql(conn, cfg["database"])
        conn.select_db(cfg["database"])

        # Bulk-load optimization: drop secondary indexes, load the rows, then
        # rebuild all indexes in one pass (much faster than incremental).
        print("2) Dropping secondary indexes for fast load ...")
        with conn.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS = 0")
            cur.execute(DROP_SECONDARY_INDEXES)
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()

        print("3) Bulk loading fact table ...")
        try:
            load_fact_table_fast(conn)
        except Exception as exc:  # noqa: BLE001
            print(f"LOAD DATA failed ({exc}); falling back to chunked inserts.")
            load_fact_table_chunked(conn)

        print("4) Rebuilding secondary indexes ...")
        with conn.cursor() as cur:
            cur.execute(ADD_SECONDARY_INDEXES)
        conn.commit()
        print("ETL finished successfully.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

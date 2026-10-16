"""
swap_database.py - Promote the staging warehouse to the final database name.

When the target database (fraudpulse_bi) is temporarily locked by a long
InnoDB rollback, the ETL is pointed at a staging database. Once the rollback
releases the schema metadata locks, this script promotes the staging schema:

  1. Drops the (empty/partial) target database if it still exists.
  2. Recreates it and moves every table + view from staging into the target.
  3. Prints a confirmation with row counts.

Usage:
    python scripts/swap_database.py --source fraudpulse_staging --target fraudpulse_bi
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pymysql

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from db_utils import get_connection, load_db_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="source (staging) database")
    parser.add_argument("--target", required=True, help="target (final) database")
    args = parser.parse_args()

    cfg = load_db_config()
    conn = get_connection(cfg)
    try:
        with conn.cursor() as cur:
            # 1) Validate the source is fully loaded
            cur.execute(
                f"SELECT COUNT(*) FROM information_schema.tables "
                f"WHERE table_schema = %s", (args.source,)
            )
            src_tables = cur.fetchone()[0]
            if src_tables == 0:
                sys.exit(f"Source database '{args.source}' is empty.")

            # 2) Drop the target database if present (idempotent promotion)
            cur.execute(f"SET FOREIGN_KEY_CHECKS = 0")
            cur.execute(f"DROP DATABASE IF EXISTS `{args.target}`")
            cur.execute(f"CREATE DATABASE `{args.target}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")

            # 3) Move every table from source to target
            cur.execute(
                f"SELECT table_name FROM information_schema.tables "
                f"WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                (args.source,),
            )
            tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                cur.execute(
                    f"RENAME TABLE `{args.source}`.`{t}` TO `{args.target}`.`{t}`"
                )
                print(f"  moved table {t}")

            # 4) Move views as well (RENAME TABLE also works on views in 8.0)
            cur.execute(
                f"SELECT table_name FROM information_schema.tables "
                f"WHERE table_schema = %s AND table_type = 'VIEW'",
                (args.source,),
            )
            views = [r[0] for r in cur.fetchall()]
            for v in views:
                cur.execute(
                    f"RENAME TABLE `{args.source}`.`{v}` TO `{args.target}`.`{v}`"
                )
                print(f"  moved view {v}")

            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
            conn.commit()

            # 5) Verify
            cur.execute(
                f"SELECT COUNT(*) FROM `{args.target}`.fact_transaction"
            )
            rows = cur.fetchone()[0]
            print(f"Promotion complete: {rows:,} rows in "
                  f"`{args.target}`.fact_transaction")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

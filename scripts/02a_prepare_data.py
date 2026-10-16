"""
02a_prepare_data.py - Prepare the raw PaySim log for warehouse loading.

Reads the raw CSV in chunks, computes business-derived columns, and writes
a cleaned "fact-ready" CSV under data/processed/. This step is database
independent and can be re-run safely.

Derived columns added by this step:
  * type_id                        - integer key for dim_transaction_type
  * amount_bucket                  - business-friendly amount band
  * orig_balance_inconsistent      - 1 if originator balance math is broken
                                     (money created / impossible state)
  * dest_balance_inconsistent      - 1 if beneficiary balance math is broken

Usage:
    python scripts/02a_prepare_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = PROJECT_ROOT / "data" / "raw" / "paysim_transactions.csv"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUT_CSV = PROCESSED_DIR / "fact_transaction_clean.csv"

# Map PaySim type strings to the ids defined in dim_transaction_type
TYPE_ID_MAP = {"PAYMENT": 1, "TRANSFER": 2, "CASH_OUT": 3, "DEBIT": 4, "CASH_IN": 5}

CHUNK = 1_000_000


def amount_bucket(amount: pd.Series) -> pd.Series:
    """Bucket a transaction amount into business-friendly bands."""
    bins = [-np.inf, 100, 1_000, 10_000, 100_000, np.inf]
    labels = [
        "Tiny (<100)",
        "Small (100-1k)",
        "Medium (1k-10k)",
        "Large (10k-100k)",
        "Huge (>100k)",
    ]
    return pd.cut(amount, bins=bins, labels=labels, right=False).astype(str)


def process_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """Apply derived-column logic to one chunk of the raw log.

    The raw PaySim CSV uses camelCase headers:
      step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig,
      nameDest, oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud
    """
    df = df.copy()
    df["type_id"] = df["type"].map(TYPE_ID_MAP).astype(np.int16)

    # Amount bucket
    df["amount_bucket"] = amount_bucket(df["amount"])

    # --- Balance-consistency flags (money-conservation checks) ---
    # Originator perspective: for CASH_IN the account *receives* money, for
    # every other type the account *sends* money.
    # tolerance = 1.0 (float rounding safety)
    tol = 1.0
    is_cash_in = df["type"] == "CASH_IN"

    expected_orig_new = np.where(
        is_cash_in,
        df["oldbalanceOrg"] + df["amount"],       # CASH_IN: new = old + amt
        df["oldbalanceOrg"] - df["amount"],       # others:  new = old - amt
    )
    df["orig_balance_inconsistent"] = (
        (df["oldbalanceOrg"] != 0)
        & (np.abs(expected_orig_new - df["newbalanceOrig"]) > tol)
    ).astype(np.int8)

    # Beneficiary perspective: new = old + amount for every type
    expected_dest_new = df["oldbalanceDest"] + df["amount"]
    df["dest_balance_inconsistent"] = (
        (df["oldbalanceDest"] != 0)
        & (np.abs(expected_dest_new - df["newbalanceDest"]) > tol)
    ).astype(np.int8)

    # Round money columns to cents to keep the fact table compact
    money_cols = [
        "amount", "oldbalanceOrg", "newbalanceOrig",
        "oldbalanceDest", "newbalanceDest",
    ]
    df[money_cols] = df[money_cols].round(2)

    # Final column layout (snake_case, matches the fact table load order)
    cols = {
        "step": "step",
        "type_id": "type_id",
        "amount": "amount",
        "nameOrig": "name_orig",
        "oldbalanceOrg": "oldbalance_org",
        "newbalanceOrig": "newbalance_orig",
        "nameDest": "name_dest",
        "oldbalanceDest": "oldbalance_dest",
        "newbalanceDest": "newbalance_dest",
        "isFraud": "is_fraud",
        "isFlaggedFraud": "is_flagged_fraud",
        "orig_balance_inconsistent": "orig_balance_inconsistent",
        "dest_balance_inconsistent": "dest_balance_inconsistent",
        "amount_bucket": "amount_bucket",
    }
    df = df[list(cols.keys())].rename(columns=cols)
    return df


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if not RAW_CSV.exists():
        sys.exit(f"Raw data not found: {RAW_CSV}")

    # Also write a short ETL profile (row counts) for the report
    profile = {
        "rows_by_type": {},
        "rows_by_type_fraud": {},
        "total_rows": 0,
        "fraud_rows": 0,
    }

    first = True
    with pd.read_csv(RAW_CSV, chunksize=CHUNK, dtype={
        "nameOrig": str, "nameDest": str,
    }) as reader:
        # newline='' disables Windows \n -> \r\n translation so the emitted
        # CSV has pure '\n' line endings; otherwise LOAD DATA would swallow
        # the trailing '\r' into the last column (amount_bucket).
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as out_fh:
            for i, chunk in enumerate(reader, start=1):
                clean = process_chunk(chunk)
                # Defensive: guarantee clean string cells (no stray CR/LF)
                for col in clean.select_dtypes(include=["object", "string"]).columns:
                    clean[col] = clean[col].str.strip().str.replace("\r", "").str.replace("\n", " ")
                clean.to_csv(
                    out_fh, header=first, index=False, line_terminator="\n",
                )
                first = False

            # Accumulate profile stats (from the raw chunk, before rename)
            profile["total_rows"] += len(chunk)
            profile["fraud_rows"] += int(chunk["isFraud"].sum())
            for t, cnt in chunk["type"].value_counts().items():
                profile["rows_by_type"][t] = profile["rows_by_type"].get(t, 0) + int(cnt)
            for (t, isf), cnt in chunk.groupby(["type", "isFraud"]).size().items():
                key = f"{t}:{isf}"
                profile["rows_by_type_fraud"][key] = profile["rows_by_type_fraud"].get(key, 0) + int(cnt)
            print(f"chunk {i}: {len(clean):,} rows (cumulative {profile['total_rows']:,})")

    # Persist profile
    import json
    with open(PROCESSED_DIR / "etl_profile.json", "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, ensure_ascii=False)

    print("=" * 60)
    print(f"Done. Clean fact CSV written to: {OUT_CSV}")
    print(f"Total rows: {profile['total_rows']:,} | Fraud rows: {profile['fraud_rows']:,}")


if __name__ == "__main__":
    main()

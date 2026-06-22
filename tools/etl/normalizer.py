"""
Normalize a raw DataFrame to the canonical Lucid transaction shape.

Handles:
  - sep=; strip (Excel metadata rows)
  - CHF amount resolution (debit_credit prefers Debit over Amount)
  - Date ISO conversion (UTC midnight)
  - Outflow negation
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ingest.csv_normalize import parse_date_to_utc, signed_amount_from_row


def normalize_dataframe(
    df: pd.DataFrame,
    column_map: dict[str, str],
    sign_rule: str,
) -> pd.DataFrame:
    """Return a normalized DataFrame with columns: date, merchant, amount, currency.

    Rows with unparseable dates or zero/null amounts are dropped.
    Amounts are negative for outflows (Lucid convention).
    """
    records: list[dict[str, Any]] = []
    raw_rows = df.to_dict(orient="records")

    for row in raw_rows:
        # Normalize row keys: strip whitespace
        row = {str(k).strip(): str(v).strip() for k, v in row.items()}

        date_key = column_map.get("date", "")
        ts = parse_date_to_utc(row.get(date_key, ""))
        if ts is None:
            continue

        amt = signed_amount_from_row(row, column_map, sign_rule)
        if amt is None or amt == 0.0:
            continue

        merchant_key = column_map.get("merchant", "")
        merchant = row.get(merchant_key, "").strip() or "(no description)"

        currency_key = column_map.get("currency", "")
        currency = row.get(currency_key, "CHF").strip().upper() or "CHF"

        records.append(
            {
                "date": ts.date().isoformat(),
                "merchant": merchant,
                "amount": round(amt, 2),
                "currency": currency,
            }
        )

    return pd.DataFrame(records, columns=["date", "merchant", "amount", "currency"])

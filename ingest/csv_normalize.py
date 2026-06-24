"""
Normalize CSV cell values: Swiss/EU decimals, common date formats, CHF amounts.

Output convention: amount negative = outflow, positive = inflow (matches
``contracts.Transaction``). Timestamps are stored as timezone-aware UTC.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def parse_decimal(raw: str) -> float | None:
    """Parse '1'234.56', '1234,56', '- 50.00' into float."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in {"-", "—", ""}:
        return None
    s = s.replace("'", "").replace("’", "").replace(" ", "")
    # European: comma decimal
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    elif s.count(",") == 1 and s.count(".") > 0:
        # 1.234,56 -> remove thousands dots
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date_to_utc(raw: str) -> datetime | None:
    """Parse common Swiss / ISO date strings; return UTC midnight for date-only."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = re.sub(r"\s+", " ", s)
    # strip time if present crudely for date-only formats
    date_part = s.split(" ")[0].split("T")[0]

    fmts = (
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y.%m.%d",
    )
    for fmt in fmts:
        try:
            d = datetime.strptime(date_part, fmt)
            return d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # ISO with time
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def signed_amount_from_row(
    row: dict[str, Any],
    column_map: dict[str, str],
    sign_rule: str,
) -> float | None:
    """Return signed CHF amount (negative=outflow) or None if row is empty.

    sign_rule values:
      single_amount         — column already uses Lucid sign convention (negative=outflow)
      single_amount_flipped — column uses credit-card convention (positive=outflow); negated here
      debit_credit          — two separate columns for debits and credits
    """
    if sign_rule in ("single_amount", "single_amount_flipped"):
        key = column_map.get("amount")
        if not key:
            return None
        val = parse_decimal(row.get(key, ""))
        if val is None:
            return None
        return -val if sign_rule == "single_amount_flipped" else val

    if sign_rule == "debit_credit":
        dk = column_map.get("debit")
        ck = column_map.get("credit")
        if not dk:
            return None
        debit = parse_decimal(row.get(dk, "")) or 0.0
        credit = (parse_decimal(row.get(ck, "")) if ck else None) or 0.0
        if debit and credit:
            # ambiguous row — prefer debit as spend if both set
            if debit >= credit:
                return -abs(debit)
            return abs(credit)
        if debit:
            return -abs(debit)
        if credit:
            return abs(credit)
        return None

    return None


def normalize_currency(row: dict[str, Any], column_map: dict[str, str]) -> str:
    ck = column_map.get("currency")
    if ck:
        c = str(row.get(ck, "")).strip().upper()
        if len(c) == 3:
            return c
    return "CHF"

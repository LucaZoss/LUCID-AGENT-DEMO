"""
Reusable query helpers for the authoritative SQLite ledger.

These are pure DB reads — no LLM, no side effects.  Import them from the
router or any deterministic tool; never inline the SQL elsewhere.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from contracts import Transaction

VALID_BUCKETS: frozenset[str] = frozenset({"need", "want", "savings"})


def get_transactions_by_bucket(
    conn: sqlite3.Connection,
    user_id: str,
    bucket: str,
    *,
    days: int = 90,
) -> list[Transaction]:
    """Return outflow transactions filtered by need/want/savings bucket.

    Only transactions where category IS NOT NULL and matches *bucket* are
    returned.  Use this when the user asks about spending within a specific
    budget label — not a raw bank category.
    """
    if bucket not in VALID_BUCKETS:
        raise ValueError(
            f"Invalid bucket {bucket!r}; expected one of {sorted(VALID_BUCKETS)}"
        )
    rows = conn.execute(
        "SELECT t.id, t.account_id, t.amount, t.currency, t.merchant, "
        "t.category, t.line_category, t.ts, t.import_batch_id, t.external_fingerprint "
        "FROM transactions t JOIN accounts a ON t.account_id = a.id "
        "WHERE a.user_id = ? AND t.category = ? "
        "AND t.ts >= datetime('now', ?) "
        "ORDER BY t.ts DESC",
        (user_id, bucket, f"-{days} days"),
    ).fetchall()
    return [_row_to_txn(r) for r in rows]


def get_transactions_by_line_category(
    conn: sqlite3.Connection,
    user_id: str,
    line_category: str,
    *,
    days: int = 90,
) -> list[Transaction]:
    """Return transactions whose raw bank category label contains *line_category*.

    Matches case-insensitively via LIKE so partial strings work (e.g. 'groc'
    matches 'Groceries').  This field comes verbatim from the CSV category
    column and is separate from the need/want/savings bucket.
    """
    if not line_category.strip():
        raise ValueError("line_category must be a non-empty string")
    rows = conn.execute(
        "SELECT t.id, t.account_id, t.amount, t.currency, t.merchant, "
        "t.category, t.line_category, t.ts, t.import_batch_id, t.external_fingerprint "
        "FROM transactions t JOIN accounts a ON t.account_id = a.id "
        "WHERE a.user_id = ? AND t.line_category LIKE ? "
        "AND t.ts >= datetime('now', ?) "
        "ORDER BY t.ts DESC",
        (user_id, f"%{line_category}%", f"-{days} days"),
    ).fetchall()
    return [_row_to_txn(r) for r in rows]


def _row_to_txn(r: tuple) -> Transaction:
    return Transaction(
        id=r[0],
        account_id=r[1],
        amount=r[2],
        currency=r[3],
        merchant=r[4],
        category=r[5],
        line_category=r[6],
        ts=datetime.fromisoformat(r[7]),
        import_batch_id=r[8],
        external_fingerprint=r[9],
    )

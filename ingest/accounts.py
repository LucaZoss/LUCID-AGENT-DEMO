"""
Account upsert helper for the CSV import pipeline.

Matches by (user_id, name) so re-importing the same file doesn't create
duplicate account rows. On conflict: updates account_type and has_income
in case the user corrected the inference.
"""

from __future__ import annotations

import sqlite3
import uuid


def upsert_account(
    conn: sqlite3.Connection,
    user_id: str,
    name: str,
    account_type: str,
    has_income: bool,
    *,
    currency: str = "CHF",
) -> str:
    """Return account_id, creating or updating the accounts row as needed."""
    row = conn.execute(
        "SELECT id FROM accounts WHERE user_id=? AND name=?",
        (user_id, name),
    ).fetchone()

    if row:
        account_id = row[0]
        conn.execute(
            "UPDATE accounts SET account_type=?, has_income=? WHERE id=?",
            (account_type, int(has_income), account_id),
        )
        conn.commit()
        return account_id

    account_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO accounts (id, user_id, name, balance, currency, account_type, has_income) "
        "VALUES (?, ?, ?, 0.0, ?, ?, ?)",
        (account_id, user_id, name, currency, account_type, int(has_income)),
    )
    conn.commit()
    return account_id

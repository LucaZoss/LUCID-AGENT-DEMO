"""
Deterministic tool implementations for the Budget Onboarding flow.

All functions are pure Python — no LLM. They operate on the live DB
after the ETL Loader and Labeller have run.
"""

from __future__ import annotations

import sqlite3
from typing import Any

# line_category values that are almost certainly essential spending
_NEEDS_CATEGORIES: frozenset[str] = frozenset({
    "Grocery Stores",
    "Supermarkets",
    "Pharmacies",
    "Health & Wellness",
    "Insurance",
    "Utilities",
    "Rent",
    "Housing",
    "Public Transport",
    "Transport",
    "Telecommunications",
    "Healthcare",
    "Medical Services",
    "Education",
    "Childcare",
    "Fuel",
    "Gas Stations",
})


def fetch_income_candidates(
    conn: sqlite3.Connection, user_id: str
) -> dict[str, Any]:
    """Return credit (inflow) transactions grouped by merchant, sorted by total."""
    rows = conn.execute(
        "SELECT t.merchant, COUNT(*) AS cnt, SUM(t.amount) AS total "
        "FROM transactions t JOIN accounts a ON t.account_id = a.id "
        "WHERE a.user_id = ? AND t.amount > 0 "
        "GROUP BY t.merchant ORDER BY total DESC",
        (user_id,),
    ).fetchall()
    return {
        "groups": [
            {"merchant": r[0], "count": r[1], "total_chf": round(r[2], 2)}
            for r in rows
        ],
        "total_inflow_chf": round(sum(r[2] for r in rows), 2),
    }


def fetch_outflow_line_categories(
    conn: sqlite3.Connection, user_id: str
) -> dict[str, Any]:
    """Return unique line_category values for outflows with counts and totals."""
    rows = conn.execute(
        "SELECT COALESCE(t.line_category, '(uncategorised)') AS cat, "
        "COUNT(*) AS cnt, SUM(t.amount) AS total "
        "FROM transactions t JOIN accounts a ON t.account_id = a.id "
        "WHERE a.user_id = ? AND t.amount < 0 "
        "GROUP BY cat ORDER BY total ASC",
        (user_id,),
    ).fetchall()
    categories = [
        {
            "line_category": r[0],
            "count": r[1],
            "total_chf": round(r[2], 2),
            "suggested_need": r[0] in _NEEDS_CATEGORIES,
        }
        for r in rows
    ]
    return {"categories": categories}


def apply_income_account(
    conn: sqlite3.Connection, user_id: str, account_id: str
) -> dict[str, Any]:
    """Mark the given account as income-bearing (has_income = 1)."""
    conn.execute(
        "UPDATE accounts SET has_income = 1 WHERE id = ? AND user_id = ?",
        (account_id, user_id),
    )
    conn.commit()
    return {"ok": True, "account_id": account_id}


def apply_category_by_line_categories(
    conn: sqlite3.Connection,
    user_id: str,
    line_categories: list[str],
    category: str,
) -> dict[str, Any]:
    """Set category on outflow transactions whose line_category is in the list."""
    if not line_categories:
        return {"ok": True, "updated": 0}
    placeholders = ",".join("?" * len(line_categories))
    cur = conn.execute(
        f"UPDATE transactions SET category = ? "
        f"WHERE account_id IN (SELECT id FROM accounts WHERE user_id = ?) "
        f"AND amount < 0 AND line_category IN ({placeholders})",
        [category, user_id] + line_categories,
    )
    conn.commit()
    return {"ok": True, "updated": cur.rowcount}


def apply_remaining_outflows_as_wants(
    conn: sqlite3.Connection, user_id: str
) -> dict[str, Any]:
    """Set category='want' on all outflow transactions still without a category."""
    cur = conn.execute(
        "UPDATE transactions SET category = 'want' "
        "WHERE account_id IN (SELECT id FROM accounts WHERE user_id = ?) "
        "AND amount < 0 AND category IS NULL",
        (user_id,),
    )
    conn.commit()
    return {"ok": True, "updated": cur.rowcount}


def apply_remaining_credits_as_savings(
    conn: sqlite3.Connection, user_id: str
) -> dict[str, Any]:
    """Set category='savings' on credit transactions still without a category."""
    cur = conn.execute(
        "UPDATE transactions SET category = 'savings' "
        "WHERE account_id IN (SELECT id FROM accounts WHERE user_id = ?) "
        "AND amount > 0 AND category IS NULL",
        (user_id,),
    )
    conn.commit()
    return {"ok": True, "updated": cur.rowcount}


def set_capital_balance(
    conn: sqlite3.Connection, user_id: str, account_id: str, amount: float
) -> dict[str, Any]:
    """Overwrite the account balance with the user-supplied capital figure."""
    conn.execute(
        "UPDATE accounts SET balance = ? WHERE id = ? AND user_id = ?",
        (round(amount, 2), account_id, user_id),
    )
    conn.commit()
    return {"ok": True, "balance": round(amount, 2)}

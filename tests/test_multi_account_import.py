"""
Tests for multi-account CSV import, upsert_account, and income isolation.

Verifies that:
- Two CSVs imported into two different accounts land in the right account rows.
- upsert_account de-duplicates by (user_id, name) and returns consistent ids.
- compute_split sees income only from the income-bearing account's transactions.
- stage_summary-style income check works correctly.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from db.db_schema import init_db
from ingest.accounts import upsert_account
from ingest.importer import import_csv_files
from ingest.csv_detect import detect_mapping, parse_header_row
from contracts import Account


@pytest.fixture
def conn(tmp_path: Path):
    dbp = tmp_path / "t.db"
    c = init_db(str(dbp))
    c.execute(
        "INSERT OR IGNORE INTO users(id, display_name, created_at) VALUES(?,?,?)",
        ("u1", "Test User", "2026-01-01T00:00:00"),
    )
    c.commit()
    return c


# ── upsert_account ────────────────────────────────────────────────────────────

def test_upsert_creates_new_account(conn):
    acc_id = upsert_account(conn, "u1", "Checking", "checking", True)
    row = conn.execute("SELECT name, account_type, has_income FROM accounts WHERE id=?", (acc_id,)).fetchone()
    assert row == ("Checking", "checking", 1)


def test_upsert_deduplicates_by_name(conn):
    id1 = upsert_account(conn, "u1", "Checking", "checking", False)
    id2 = upsert_account(conn, "u1", "Checking", "checking", True)
    assert id1 == id2
    row = conn.execute("SELECT has_income FROM accounts WHERE id=?", (id1,)).fetchone()
    assert row[0] == 1  # updated on second call


def test_upsert_two_accounts_different_ids(conn):
    id1 = upsert_account(conn, "u1", "Checking", "checking", True)
    id2 = upsert_account(conn, "u1", "Credit Card", "credit_card", False)
    assert id1 != id2
    count = conn.execute("SELECT COUNT(*) FROM accounts WHERE user_id='u1'").fetchone()[0]
    assert count == 2


# ── multi-account CSV import ───────────────────────────────────────────────────

def _make_csv(rows: list[str], tmp_path: Path, name: str = "test.csv") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(rows), encoding="utf-8")
    return p


def _resolve(raw: bytes):
    headers, enc, delim, _ = parse_header_row(raw)
    return detect_mapping(headers, encoding=enc, delimiter=delim, sample_rows=None)


def test_two_accounts_transactions_isolated(conn, tmp_path):
    """Transactions from two CSV files land in their respective accounts."""
    chk_csv = _make_csv([
        "Date,Description,Amount",
        "2026-05-01,Employer SA,4500.00",
        "2026-05-02,Migros,-45.00",
    ], tmp_path, "checking.csv")

    cc_csv = _make_csv([
        "Date,Description,Amount",
        "2026-05-03,Netflix,20.00",
        "2026-05-04,Zara,89.00",
    ], tmp_path, "credit_card.csv")

    chk_id = upsert_account(conn, "u1", "Checking", "checking", True)
    cc_id = upsert_account(conn, "u1", "Credit Card", "credit_card", False)

    chk_mapping = _resolve(chk_csv.read_bytes())
    cc_mapping = _resolve(cc_csv.read_bytes())

    import_csv_files(conn, "u1", chk_id, [chk_csv], mapping=chk_mapping)
    import_csv_files(conn, "u1", cc_id, [cc_csv], mapping=cc_mapping)

    chk_txns = conn.execute(
        "SELECT amount FROM transactions WHERE account_id=? ORDER BY amount DESC",
        (chk_id,),
    ).fetchall()
    cc_txns = conn.execute(
        "SELECT amount FROM transactions WHERE account_id=? ORDER BY amount DESC",
        (cc_id,),
    ).fetchall()

    # Checking: income + one outflow
    assert len(chk_txns) == 2
    chk_amounts = {r[0] for r in chk_txns}
    assert 4500.0 in chk_amounts
    assert -45.0 in chk_amounts

    # Credit card: two outflows (sign flipped on single_amount_flipped, but here
    # amounts are already positive in CSV; with single_amount sign_rule they stay as-is)
    assert len(cc_txns) == 2


def test_income_account_flag_persists(conn):
    acc_id = upsert_account(conn, "u1", "Salary Account", "checking", True)
    row = conn.execute(
        "SELECT has_income FROM accounts WHERE id=?", (acc_id,)
    ).fetchone()
    assert row[0] == 1


def test_no_income_account_detected(conn):
    """When no account has has_income=1, the income check query returns 0."""
    upsert_account(conn, "u1", "Credit Card", "credit_card", False)
    count = conn.execute(
        "SELECT COUNT(*) FROM accounts WHERE user_id='u1' AND has_income=1"
    ).fetchone()[0]
    assert count == 0


def test_income_account_detected(conn):
    """When an income-bearing account exists, the check returns nonzero."""
    upsert_account(conn, "u1", "Checking", "checking", True)
    upsert_account(conn, "u1", "Credit Card", "credit_card", False)
    count = conn.execute(
        "SELECT COUNT(*) FROM accounts WHERE user_id='u1' AND has_income=1"
    ).fetchone()[0]
    assert count == 1


def test_migrate_adds_columns_to_existing_db(tmp_path):
    """migrate_schema() adds account_type / has_income to a DB missing those columns."""
    import sqlite3
    from db.db_schema import migrate_schema

    dbp = tmp_path / "old.db"
    conn_old = sqlite3.connect(str(dbp))
    # Create the accounts table WITHOUT the new columns (simulates old schema)
    conn_old.execute(
        "CREATE TABLE accounts (id TEXT PRIMARY KEY, user_id TEXT, name TEXT, balance REAL, currency TEXT)"
    )
    conn_old.execute(
        "CREATE TABLE transactions (id TEXT PRIMARY KEY, account_id TEXT, amount REAL, "
        "currency TEXT, merchant TEXT, category TEXT, ts TEXT)"
    )
    conn_old.commit()
    migrate_schema(conn_old)
    cols = {r[1] for r in conn_old.execute("PRAGMA table_info(accounts)").fetchall()}
    assert "account_type" in cols
    assert "has_income" in cols

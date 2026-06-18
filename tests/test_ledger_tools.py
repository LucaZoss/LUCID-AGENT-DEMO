"""Tests for ledger categorization proposal tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents import ledger_tools
from db.db_schema import init_db


@pytest.fixture
def conn(tmp_path: Path):
    dbp = tmp_path / "l.db"
    c = init_db(str(dbp))
    c.execute(
        "INSERT OR IGNORE INTO users(id, display_name, created_at) VALUES(?,?,?)",
        ("u1", "T", "2026-01-01T00:00:00"),
    )
    c.execute(
        "INSERT OR IGNORE INTO accounts(id, user_id, name, balance, currency) "
        "VALUES(?,?,?,?,?)",
        ("acc1", "u1", "CHK", 0.0, "CHF"),
    )
    c.execute(
        "INSERT INTO transactions(id, account_id, amount, currency, merchant, "
        "category, line_category, ts, import_batch_id, external_fingerprint) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "t1",
            "acc1",
            -50.0,
            "CHF",
            "Coop",
            None,
            None,
            "2026-01-15T12:00:00+00:00",
            None,
            None,
        ),
    )
    c.commit()
    return c


def test_propose_bucket_invalid(conn) -> None:
    r = ledger_tools.propose_spending_bucket(
        conn, "u1", "t1", "Coop", "luxury",
    )
    assert r["ok"] is False


def test_propose_and_apply(conn) -> None:
    r1 = ledger_tools.propose_spending_bucket(
        conn, "u1", "t1", "Coop", "need", rationale="groceries",
    )
    assert r1["ok"] is True
    pid = r1["proposal_id"]
    r2 = ledger_tools.propose_line_category(
        conn, "u1", "t1", "Coop", "groceries",
    )
    assert r2["ok"] is True
    ap = ledger_tools.apply_proposal(conn, "u1", pid)
    assert ap["ok"] is True
    row = conn.execute(
        "SELECT category, line_category FROM transactions WHERE id=?",
        ("t1",),
    ).fetchone()
    assert row[0] == "need"
    assert row[1] == "groceries"

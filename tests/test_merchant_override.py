"""
Tests for merchant memory:
- apply_proposal writes to merchant_category_overrides
- ledger_categorizer pre-fills known merchants from overrides
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from db.db_schema import init_db
from agents.ledger_tools import apply_proposal, propose_spending_bucket, propose_line_category
from ingest.accounts import upsert_account


@pytest.fixture
def conn(tmp_path: Path):
    dbp = tmp_path / "t.db"
    c = init_db(str(dbp))
    c.execute(
        "INSERT OR IGNORE INTO users(id, display_name, created_at) VALUES(?,?,?)",
        ("u1", "Test", "2026-01-01T00:00:00"),
    )
    c.commit()
    return c


@pytest.fixture
def acc_id(conn):
    return upsert_account(conn, "u1", "Checking", "checking", True)


def _insert_txn(conn, acc_id: str, merchant: str, amount: float = -30.0) -> str:
    txn_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO transactions(id, account_id, amount, currency, merchant, ts) "
        "VALUES(?,?,?,?,?,?)",
        (txn_id, acc_id, amount, "CHF", merchant, "2026-05-01T00:00:00"),
    )
    conn.commit()
    return txn_id


def _make_proposal(conn, txn_id: str, bucket: str = "want", line: str = "dining") -> str:
    return propose_spending_bucket(conn, "u1", txn_id, "Starbucks", bucket)["proposal_id"]


# ── apply_proposal → merchant_category_overrides ──────────────────────────────

def test_apply_proposal_writes_override(conn, acc_id):
    """Accepting a proposal records the merchant → category in overrides."""
    txn_id = _insert_txn(conn, acc_id, "Starbucks")
    pid = propose_spending_bucket(conn, "u1", txn_id, "Starbucks", "want")["proposal_id"]
    apply_proposal(conn, "u1", pid)

    row = conn.execute(
        "SELECT bucket, line_category FROM merchant_category_overrides "
        "WHERE user_id='u1' AND merchant_normalized='starbucks'"
    ).fetchone()
    assert row is not None
    assert row[0] == "want"


def test_apply_proposal_writes_line_override(conn, acc_id):
    """Accepting with a line override records both bucket and line."""
    txn_id = _insert_txn(conn, acc_id, "Migros")
    pid = propose_spending_bucket(conn, "u1", txn_id, "Migros", "need")["proposal_id"]
    apply_proposal(conn, "u1", pid, line_override="groceries")

    row = conn.execute(
        "SELECT bucket, line_category FROM merchant_category_overrides "
        "WHERE merchant_normalized='migros'"
    ).fetchone()
    assert row[0] == "need"
    assert row[1] == "groceries"


def test_apply_proposal_updates_existing_override(conn, acc_id):
    """Second accept for same merchant upserts (doesn't create duplicate)."""
    txn1 = _insert_txn(conn, acc_id, "Netflix", amount=-15.0)
    txn2 = _insert_txn(conn, acc_id, "Netflix", amount=-15.0)
    pid1 = propose_spending_bucket(conn, "u1", txn1, "Netflix", "want")["proposal_id"]
    pid2 = propose_spending_bucket(conn, "u1", txn2, "Netflix", "want")["proposal_id"]
    apply_proposal(conn, "u1", pid1)
    apply_proposal(conn, "u1", pid2, bucket_override="need")

    rows = conn.execute(
        "SELECT bucket FROM merchant_category_overrides WHERE merchant_normalized='netflix'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "need"


def test_apply_proposal_no_override_without_bucket_or_line(conn, acc_id):
    """If both bucket and line are empty, no override is written."""
    txn_id = _insert_txn(conn, acc_id, "Unknown Corp")
    # Manually insert a proposal with no bucket/line
    pid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO category_proposals(id, user_id, txn_id, proposed_bucket, status, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (pid, "u1", txn_id, None, "pending", "2026-01-01T00:00:00"),
    )
    conn.commit()
    result = apply_proposal(conn, "u1", pid)
    assert result.get("ok") is False  # nothing to apply


# ── ledger_categorizer pre-fill ───────────────────────────────────────────────

def test_categorizer_prefills_known_merchant(conn, acc_id):
    """Run categorizer when merchant override exists — proposals created without LLM."""
    from agents.ledger_categorizer import _fetch_uncategorized_outflows, _load_merchant_overrides

    # Seed an override for "Coop"
    conn.execute(
        "INSERT INTO merchant_category_overrides(id, user_id, merchant_normalized, bucket, line_category, updated_at) "
        "VALUES(?,?,?,?,?,?)",
        (str(uuid.uuid4()), "u1", "coop", "need", "groceries", "2026-01-01T00:00:00"),
    )
    conn.commit()

    txn_id = _insert_txn(conn, acc_id, "Coop")

    overrides = _load_merchant_overrides(conn, "u1")
    assert "coop" in overrides
    assert overrides["coop"] == ("need", "groceries", None)

    # Simulate what the categorizer does for known merchants
    propose_spending_bucket(conn, "u1", txn_id, "Coop", "need", rationale="merchant memory")
    propose_line_category(conn, "u1", txn_id, "Coop", "groceries", rationale="merchant memory")

    # propose_spending_bucket and propose_line_category both merge into ONE proposal row
    rows = conn.execute(
        "SELECT proposed_bucket, proposed_line, rationale FROM category_proposals WHERE txn_id=?",
        (txn_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "need"
    assert rows[0][1] == "groceries"
    assert rows[0][2] == "merchant memory"


def test_load_merchant_overrides_empty(conn):
    """No overrides → empty dict."""
    from agents.ledger_categorizer import _load_merchant_overrides
    assert _load_merchant_overrides(conn, "u1") == {}


def test_load_merchant_overrides_multiple(conn):
    """Multiple overrides are all returned."""
    from agents.ledger_categorizer import _load_merchant_overrides

    for merchant, bucket in [("migros", "need"), ("netflix", "want"), ("viac", "savings")]:
        conn.execute(
            "INSERT OR REPLACE INTO merchant_category_overrides"
            "(id, user_id, merchant_normalized, bucket, line_category, updated_at) VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), "u1", merchant, bucket, None, "2026-01-01T00:00:00"),
        )
    conn.commit()

    overrides = _load_merchant_overrides(conn, "u1")
    assert set(overrides.keys()) == {"migros", "netflix", "viac"}
    assert overrides["migros"] == ("need", None, None)

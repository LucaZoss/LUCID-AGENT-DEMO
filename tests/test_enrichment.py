"""Tests for deterministic transaction enrichment (tools/enrichment.py)."""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from db.db_schema import init_db
from tools.enrichment import (
    auto_normalize_categories,
    classify_fixed_variable,
    detect_recurring,
    detect_transfers,
    enrich_transactions,
    score_confidence,
)

USER_ID = "test-enrich-user"
ACCOUNT_ID = "test-enrich-acct"


@pytest.fixture()
def conn():
    c = init_db(":memory:")
    c.execute(
        "INSERT INTO users(id, display_name, created_at) VALUES(?,?,'2026-01-01')",
        (USER_ID, "Test User"),
    )
    c.execute(
        "INSERT INTO accounts(id, user_id, name, balance, currency) "
        "VALUES(?,?,'Checking',0.0,'CHF')",
        (ACCOUNT_ID, USER_ID),
    )
    c.commit()
    return c


def _txn(
    conn: sqlite3.Connection,
    txn_id: str,
    merchant: str,
    amount: float,
    ts: str,
    normalized_category: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO transactions"
        "(id, account_id, amount, currency, merchant, normalized_category, ts) "
        "VALUES(?,?,?,'CHF',?,?,?)",
        (txn_id, ACCOUNT_ID, amount, merchant, normalized_category, ts),
    )
    conn.commit()


# ── auto_normalize_categories ────────────────────────────────────────────────

class TestAutoNormalize:
    def test_line_category_mapped(self, conn):
        # "rent" line_category should resolve to "rent" normalized key
        _txn(conn, "n1", "Miete Zurich", -1800.0, "2026-01-01T10:00:00")
        conn.execute(
            "UPDATE transactions SET line_category='rent' WHERE id='n1'"
        )
        conn.commit()
        count = auto_normalize_categories(conn, USER_ID)
        assert count == 1
        norm = conn.execute(
            "SELECT normalized_category FROM transactions WHERE id='n1'"
        ).fetchone()[0]
        assert norm == "rent"

    def test_merchant_pattern_matched(self, conn):
        # Migros → groceries_food via merchant pattern
        _txn(conn, "n2", "Migros Supermarkt", -55.0, "2026-01-02T10:00:00")
        auto_normalize_categories(conn, USER_ID)
        norm = conn.execute(
            "SELECT normalized_category FROM transactions WHERE id='n2'"
        ).fetchone()[0]
        assert norm == "groceries_food"

    def test_positive_amount_salary_fallback(self, conn):
        _txn(conn, "n3", "Unknown Employer", 5000.0, "2026-01-03T10:00:00")
        auto_normalize_categories(conn, USER_ID)
        norm = conn.execute(
            "SELECT normalized_category FROM transactions WHERE id='n3'"
        ).fetchone()[0]
        assert norm == "salary"

    def test_existing_normalized_not_overwritten(self, conn):
        _txn(conn, "n4", "Migros", -40.0, "2026-01-04T10:00:00", normalized_category="wants_other")
        count = auto_normalize_categories(conn, USER_ID)
        assert count == 0  # already set, skipped
        norm = conn.execute(
            "SELECT normalized_category FROM transactions WHERE id='n4'"
        ).fetchone()[0]
        assert norm == "wants_other"

    def test_unknown_outflow_stays_null(self, conn):
        _txn(conn, "n5", "Totally Unknown Corp", -25.0, "2026-01-05T10:00:00")
        auto_normalize_categories(conn, USER_ID)
        norm = conn.execute(
            "SELECT normalized_category FROM transactions WHERE id='n5'"
        ).fetchone()[0]
        assert norm is None


# ── detect_transfers ─────────────────────────────────────────────────────────

class TestDetectTransfers:
    def test_twint_in_merchant_name(self, conn):
        _txn(conn, "t1", "TWINT Payment", -20.0, "2026-01-01T10:00:00")
        assert detect_transfers(conn, USER_ID) == 1
        is_t = conn.execute("SELECT is_transfer FROM transactions WHERE id='t1'").fetchone()[0]
        assert is_t == 1

    def test_twint_credit_category(self, conn):
        _txn(conn, "t2", "Random Name", 15.0, "2026-01-02T10:00:00", normalized_category="twint_credit")
        assert detect_transfers(conn, USER_ID) == 1

    def test_twint_debit_category(self, conn):
        _txn(conn, "t3", "Random Name", -15.0, "2026-01-03T10:00:00", normalized_category="twint_debit")
        assert detect_transfers(conn, USER_ID) == 1

    def test_sepa_merchant(self, conn):
        _txn(conn, "t4", "SEPA Überweisung an Konto", -500.0, "2026-01-04T10:00:00")
        assert detect_transfers(conn, USER_ID) == 1

    def test_regular_spend_not_flagged(self, conn):
        _txn(conn, "t5", "Migros", -55.0, "2026-01-05T10:00:00", normalized_category="groceries_food")
        assert detect_transfers(conn, USER_ID) == 0
        is_t = conn.execute("SELECT is_transfer FROM transactions WHERE id='t5'").fetchone()[0]
        assert is_t == 0


# ── detect_recurring ─────────────────────────────────────────────────────────

class TestDetectRecurring:
    def test_monthly_cadence(self, conn):
        _txn(conn, "r0", "Helsana", -420.0, "2026-01-01T10:00:00")
        _txn(conn, "r1", "Helsana", -420.0, "2026-02-01T10:00:00")
        _txn(conn, "r2", "Helsana", -420.0, "2026-03-01T10:00:00")
        count = detect_recurring(conn, USER_ID)
        assert count == 3
        rows = conn.execute(
            "SELECT is_recurring, recurrence_cadence FROM transactions WHERE merchant='Helsana'"
        ).fetchall()
        for is_rec, cadence in rows:
            assert is_rec == 1
            assert cadence == "monthly"

    def test_weekly_cadence(self, conn):
        _txn(conn, "w0", "Saturday Market", -30.0, "2026-01-03T10:00:00")
        _txn(conn, "w1", "Saturday Market", -30.0, "2026-01-10T10:00:00")
        _txn(conn, "w2", "Saturday Market", -30.0, "2026-01-17T10:00:00")
        count = detect_recurring(conn, USER_ID)
        assert count == 3
        cadences = {
            r[0]
            for r in conn.execute(
                "SELECT recurrence_cadence FROM transactions WHERE merchant='Saturday Market'"
            ).fetchall()
        }
        assert cadences == {"weekly"}

    def test_one_off_not_marked(self, conn):
        _txn(conn, "o1", "Zara", -89.0, "2026-01-15T10:00:00")
        detect_recurring(conn, USER_ID)
        is_r = conn.execute("SELECT is_recurring FROM transactions WHERE id='o1'").fetchone()[0]
        assert is_r == 0

    def test_transfers_excluded_from_recurring(self, conn):
        # Two TWINT transactions 30 days apart — should NOT be flagged recurring
        _txn(conn, "x0", "TWINT Payment", -50.0, "2026-01-01T10:00:00")
        _txn(conn, "x1", "TWINT Payment", -50.0, "2026-02-01T10:00:00")
        detect_transfers(conn, USER_ID)   # marks both as transfers
        count = detect_recurring(conn, USER_ID)
        assert count == 0


# ── classify_fixed_variable ───────────────────────────────────────────────────

class TestClassifyFixed:
    def test_rent_is_fixed(self, conn):
        _txn(conn, "f1", "Miete Zurich", -1800.0, "2026-01-01T10:00:00", normalized_category="rent")
        assert classify_fixed_variable(conn, USER_ID) == 1
        is_f = conn.execute("SELECT is_fixed FROM transactions WHERE id='f1'").fetchone()[0]
        assert is_f == 1

    def test_health_insurance_is_fixed(self, conn):
        _txn(conn, "f2", "Helsana", -420.0, "2026-01-01T10:00:00", normalized_category="health_insurance")
        classify_fixed_variable(conn, USER_ID)
        is_f = conn.execute("SELECT is_fixed FROM transactions WHERE id='f2'").fetchone()[0]
        assert is_f == 1

    def test_telecom_is_fixed(self, conn):
        _txn(conn, "f3", "Swisscom", -79.0, "2026-01-01T10:00:00", normalized_category="telecom")
        classify_fixed_variable(conn, USER_ID)
        is_f = conn.execute("SELECT is_fixed FROM transactions WHERE id='f3'").fetchone()[0]
        assert is_f == 1

    def test_restaurants_is_variable(self, conn):
        _txn(conn, "f4", "Tibits", -45.0, "2026-01-05T10:00:00", normalized_category="restaurants")
        classify_fixed_variable(conn, USER_ID)
        is_f = conn.execute("SELECT is_fixed FROM transactions WHERE id='f4'").fetchone()[0]
        assert is_f == 0

    def test_uncategorized_skipped(self, conn):
        _txn(conn, "f5", "Unknown", -10.0, "2026-01-06T10:00:00")
        count = classify_fixed_variable(conn, USER_ID)
        assert count == 0


# ── score_confidence ─────────────────────────────────────────────────────────

class TestScoreConfidence:
    def test_accepted_proposal_scores_1(self, conn):
        _txn(conn, "c1", "SomeShop", -30.0, "2026-01-10T10:00:00", normalized_category="clothing")
        conn.execute(
            "INSERT INTO category_proposals(id, user_id, txn_id, status, created_at) "
            "VALUES(?,?,'c1','accepted','2026-01-10T12:00:00')",
            (str(uuid.uuid4()), USER_ID),
        )
        conn.commit()
        score_confidence(conn, USER_ID)
        conf = conn.execute(
            "SELECT enrichment_confidence FROM transactions WHERE id='c1'"
        ).fetchone()[0]
        assert conf == 1.0

    def test_user_confirmed_override_scores_1(self, conn):
        _txn(conn, "c2", "Migros", -55.0, "2026-01-11T10:00:00", normalized_category="groceries_food")
        conn.execute(
            "INSERT INTO merchant_category_overrides"
            "(id, user_id, merchant_normalized, source, confidence, updated_at) "
            "VALUES(?,?,'migros','user_confirmed',1.0,'2026-01-11T10:00:00')",
            (str(uuid.uuid4()), USER_ID),
        )
        conn.commit()
        score_confidence(conn, USER_ID)
        conf = conn.execute(
            "SELECT enrichment_confidence FROM transactions WHERE id='c2'"
        ).fetchone()[0]
        assert conf == 1.0

    def test_no_override_gets_code_rule_confidence(self, conn):
        _txn(conn, "c3", "UnknownMerchant", -25.0, "2026-01-12T10:00:00", normalized_category="wants_other")
        score_confidence(conn, USER_ID)
        conf = conn.execute(
            "SELECT enrichment_confidence FROM transactions WHERE id='c3'"
        ).fetchone()[0]
        assert conf == 0.75

    def test_uncategorized_not_scored(self, conn):
        _txn(conn, "c4", "NoCategory", -10.0, "2026-01-13T10:00:00")
        score_confidence(conn, USER_ID)
        conf = conn.execute(
            "SELECT enrichment_confidence FROM transactions WHERE id='c4'"
        ).fetchone()[0]
        assert conf is None


# ── enrich_transactions (master runner) ──────────────────────────────────────

class TestEnrichAll:
    def test_returns_summary_dict(self, conn):
        _txn(conn, "e1", "Migros", -80.0, "2026-01-01T10:00:00", normalized_category="groceries_food")
        result = enrich_transactions(conn, USER_ID)
        assert set(result) == {
            "auto_normalized",
            "transfers_flagged",
            "recurring_detected",
            "fixed_classified",
            "confidence_scored",
        }
        assert all(isinstance(v, int) for v in result.values())

    def test_full_pipeline(self, conn):
        # Twint transfer (no pre-set normalized_category — auto_normalize will set twint_debit)
        _txn(conn, "p1", "TWINT Payment", -20.0, "2026-01-05T10:00:00")
        # Monthly recurring rent (line_category set; auto_normalize will resolve to "rent")
        for pid, ts in [("p2", "2026-01-01"), ("p3", "2026-02-01"), ("p4", "2026-03-01")]:
            _txn(conn, pid, "Miete Zurich", -1800.0, f"{ts}T10:00:00")
            conn.execute("UPDATE transactions SET line_category='rent' WHERE id=?", (pid,))
        conn.commit()

        result = enrich_transactions(conn, USER_ID)

        assert result["auto_normalized"] >= 4    # all 4 rows resolved
        assert result["transfers_flagged"] >= 1
        assert result["recurring_detected"] >= 3
        assert result["fixed_classified"] >= 3   # rent rows
        assert result["confidence_scored"] >= 4

        # Transfer row must not be marked recurring
        is_r = conn.execute(
            "SELECT is_recurring FROM transactions WHERE id='p1'"
        ).fetchone()[0]
        assert is_r == 0

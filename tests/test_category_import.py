"""Tests for CSV category column support and DB category/line_category queries."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from db.db_schema import init_db
from db.queries import get_transactions_by_bucket, get_transactions_by_line_category
from ingest.csv_detect import ResolvedColumnMapping
from ingest.importer import import_csv_files
from ingest import profiles


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def conn(tmp_path: Path):
    dbp = tmp_path / "t.db"
    c = init_db(str(dbp))
    c.execute(
        "INSERT OR IGNORE INTO users(id, display_name, created_at) VALUES(?,?,?)",
        ("u1", "Test User", "2026-01-01T00:00:00"),
    )
    c.execute(
        "INSERT OR IGNORE INTO accounts(id, user_id, name, balance, currency) "
        "VALUES(?,?,?,?,?)",
        ("acc1", "u1", "CHK", 0.0, "CHF"),
    )
    c.commit()
    return c


# ── ResolvedColumnMapping with category_col ───────────────────────────────────

def test_category_col_field_accessible() -> None:
    m = ResolvedColumnMapping(
        column_map={"date": "Datum", "merchant": "Text", "amount": "Betrag"},
        sign_rule="single_amount",
        encoding="utf-8",
        delimiter=",",
        category_col="Kategorie",
    )
    assert m.category_col == "Kategorie"


def test_category_col_defaults_to_none() -> None:
    m = ResolvedColumnMapping(
        column_map={"date": "Datum", "merchant": "Text", "amount": "Betrag"},
        sign_rule="single_amount",
        encoding="utf-8",
        delimiter=",",
    )
    assert m.category_col is None


# ── Import: category col → line_category; category stays NULL ─────────────────

def _make_csv_with_category(td: str) -> Path:
    body = (
        "Buchungsdatum,Beschreibung,Betrag,Kategorie\n"
        "2026-01-10,Coop,-12.50,Lebensmittel\n"
        "2026-01-11,Restaurant Zurich,-45.00,Gastronomie\n"
    )
    p = Path(td) / "bank.csv"
    p.write_text(body, encoding="utf-8")
    return p


def test_import_known_category_stores_line_category(conn) -> None:
    with tempfile.TemporaryDirectory() as td:
        fp = _make_csv_with_category(td)
        mapping = ResolvedColumnMapping(
            column_map={"date": "Buchungsdatum", "merchant": "Beschreibung", "amount": "Betrag"},
            sign_rule="single_amount",
            encoding="utf-8",
            delimiter=",",
            category_col="Kategorie",
        )
        results = import_csv_files(conn, "u1", "acc1", [fp], mapping=mapping)
        assert results[0].rows_inserted == 2

    rows = conn.execute(
        "SELECT line_category, category FROM transactions ORDER BY ts"
    ).fetchall()
    # Raw bank label stored verbatim
    assert rows[0][0] == "Lebensmittel"
    assert rows[1][0] == "Gastronomie"
    # Budget bucket NOT set — categorizer must decide
    assert rows[0][1] is None
    assert rows[1][1] is None


def test_import_no_category_col_line_category_null(conn) -> None:
    body = (
        "Buchungsdatum,Beschreibung,Betrag\n"
        "2026-02-01,SBB,-8.00\n"
    )
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "no_cat.csv"
        fp.write_text(body, encoding="utf-8")
        mapping = ResolvedColumnMapping(
            column_map={"date": "Buchungsdatum", "merchant": "Beschreibung", "amount": "Betrag"},
            sign_rule="single_amount",
            encoding="utf-8",
            delimiter=",",
        )
        import_csv_files(conn, "u1", "acc1", [fp], mapping=mapping)

    row = conn.execute("SELECT line_category FROM transactions LIMIT 1").fetchone()
    assert row[0] is None


def test_import_empty_category_value_not_stored(conn) -> None:
    body = (
        "Buchungsdatum,Beschreibung,Betrag,Kategorie\n"
        "2026-03-01,Migros,-20.00,\n"
    )
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "empty_cat.csv"
        fp.write_text(body, encoding="utf-8")
        mapping = ResolvedColumnMapping(
            column_map={"date": "Buchungsdatum", "merchant": "Beschreibung", "amount": "Betrag"},
            sign_rule="single_amount",
            encoding="utf-8",
            delimiter=",",
            category_col="Kategorie",
        )
        import_csv_files(conn, "u1", "acc1", [fp], mapping=mapping)

    row = conn.execute("SELECT line_category FROM transactions LIMIT 1").fetchone()
    assert row[0] is None


# ── Profile round-trip with category_col ─────────────────────────────────────

def test_profile_round_trip_category_col(conn) -> None:
    pid = profiles.save_profile(
        conn,
        "u1",
        "My Bank",
        {"date": "Datum", "merchant": "Text", "amount": "Betrag"},
        sign_rule="single_amount",
        encoding="utf-8",
        delimiter=",",
        headers=["Datum", "Text", "Betrag", "Kategorie"],
        category_col="Kategorie",
    )
    loaded = profiles.get_profile(conn, pid)
    assert loaded is not None
    assert loaded["category_col"] == "Kategorie"


def test_profile_round_trip_no_category_col(conn) -> None:
    pid = profiles.save_profile(
        conn,
        "u1",
        "No Cat",
        {"date": "Datum", "merchant": "Text", "amount": "Betrag"},
        sign_rule="single_amount",
        encoding="utf-8",
        delimiter=",",
        headers=["Datum", "Text", "Betrag"],
    )
    loaded = profiles.get_profile(conn, pid)
    assert loaded is not None
    assert loaded["category_col"] is None


# ── DB query helpers ──────────────────────────────────────────────────────────

def _seed_transactions(conn) -> None:
    rows = [
        ("t1", "acc1", -15.0, "Coop", "need", "Lebensmittel"),
        ("t2", "acc1", -45.0, "Restaurant Zurich", "want", "Gastronomie"),
        ("t3", "acc1", -400.0, "VIAC 3a", "savings", None),
        ("t4", "acc1", -12.0, "Migros", "need", "Lebensmittel"),
        ("t5", "acc1", -30.0, "Spotify", "want", "Streaming"),
    ]
    for tid, aid, amt, merch, cat, line_cat in rows:
        conn.execute(
            "INSERT INTO transactions(id, account_id, amount, currency, merchant, "
            "category, line_category, ts) VALUES(?,?,?,?,?,?,?,?)",
            (tid, aid, amt, "CHF", merch, cat, line_cat, "2026-04-01T12:00:00"),
        )
    conn.commit()


def test_get_transactions_by_bucket_need(conn) -> None:
    _seed_transactions(conn)
    txns = get_transactions_by_bucket(conn, "u1", "need")
    assert len(txns) == 2
    merchants = {t.merchant for t in txns}
    assert merchants == {"Coop", "Migros"}


def test_get_transactions_by_bucket_savings(conn) -> None:
    _seed_transactions(conn)
    txns = get_transactions_by_bucket(conn, "u1", "savings")
    assert len(txns) == 1
    assert txns[0].merchant == "VIAC 3a"


def test_get_transactions_by_bucket_invalid_raises(conn) -> None:
    with pytest.raises(ValueError, match="Invalid bucket"):
        get_transactions_by_bucket(conn, "u1", "splurge")


def test_get_transactions_by_line_category(conn) -> None:
    _seed_transactions(conn)
    txns = get_transactions_by_line_category(conn, "u1", "Lebensmittel")
    assert len(txns) == 2
    merchants = {t.merchant for t in txns}
    assert merchants == {"Coop", "Migros"}


def test_get_transactions_by_line_category_partial_match(conn) -> None:
    _seed_transactions(conn)
    txns = get_transactions_by_line_category(conn, "u1", "gastro")  # partial, case-insensitive
    assert len(txns) == 1
    assert txns[0].merchant == "Restaurant Zurich"


def test_get_transactions_by_line_category_empty_raises(conn) -> None:
    with pytest.raises(ValueError):
        get_transactions_by_line_category(conn, "u1", "  ")

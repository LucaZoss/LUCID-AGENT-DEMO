"""Tests for CSV header detection, import dedupe, profiles, and rollback."""

from __future__ import annotations

from pathlib import Path

import pytest

from db.db_schema import init_db
from ingest.csv_detect import (
    MappingAmbiguity,
    ResolvedColumnMapping,
    detect_mapping,
    find_header_row_index,
    header_row_hash,
    parse_header_row,
    strip_sep_hint,
)
from ingest.importer import import_csv_files, preview_csv_file, rollback_import_batch
from ingest import profiles


@pytest.fixture
def conn(tmp_path: Path):
    """Fresh SQLite DB with full schema."""
    dbp = tmp_path / "t.db"
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
    c.commit()
    return c


def test_parse_header_swiss_semicolon() -> None:
    """Semicolon-separated UTF-8 header parses."""
    raw = "Buchungsdatum;Begünstigter;Betrag\n2026-01-01;Coop;-10.00\n".encode("utf-8")
    headers, enc, delim, _hdr_idx = parse_header_row(raw)
    assert "Buchungsdatum" in headers
    assert delim == ";"
    assert enc.startswith("utf-8")


def test_detect_mapping_single_amount() -> None:
    raw = (
        "Buchungsdatum,Begünstigter,Betrag\n"
        "2026-01-01,Coop,-10.00\n"
    ).encode("utf-8")
    headers, enc, delim, _hdr_idx = parse_header_row(raw)
    det = detect_mapping(headers, encoding=enc, delimiter=delim)
    assert det.sign_rule == "single_amount"
    assert det.column_map["date"] == "Buchungsdatum"
    assert det.column_map["merchant"] == "Begünstigter"
    assert det.column_map["amount"] == "Betrag"


def test_header_hash_stable() -> None:
    h1 = header_row_hash(["A", "B"], ",")
    h2 = header_row_hash(["A", "B"], ",")
    assert h1 == h2


def test_import_inserts_and_skips_duplicate_rows(conn) -> None:
    import tempfile

    body = (
        "Buchungsdatum,Begünstigter,Betrag\n"
        "2026-01-01,Coop,-10.00\n"
        "2026-01-02,Migros,-5.00\n"
    )
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "x.csv"
        fp.write_text(body, encoding="utf-8")
        r1 = import_csv_files(conn, "u1", "acc1", [fp], force_reimport=False)
        assert r1[0].rows_inserted == 2
        assert r1[0].rows_skipped_duplicate == 0
        # same file bytes -> whole file skipped
        r2 = import_csv_files(conn, "u1", "acc1", [fp], force_reimport=False)
        assert r2[0].skipped is True
        # force re-import same rows -> duplicate fingerprints
        r3 = import_csv_files(conn, "u1", "acc1", [fp], force_reimport=True)
        assert r3[0].rows_inserted == 0
        assert r3[0].rows_skipped_duplicate == 2


def test_profile_save_and_reload(conn) -> None:
    raw = "Buchungsdatum,Begünstigter,Betrag\n2026-02-01,A,-1.0\n".encode("utf-8")
    headers, enc, delim, _hdr_idx = parse_header_row(raw)
    det = detect_mapping(headers, encoding=enc, delimiter=delim)
    assert isinstance(det, ResolvedColumnMapping)
    pid = profiles.save_profile(
        conn,
        "u1",
        "testprof",
        det.column_map,
        sign_rule=det.sign_rule,
        encoding=det.encoding,
        delimiter=det.delimiter,
        headers=headers,
    )
    loaded = profiles.find_profile_by_header_hash(
        conn, "u1", header_row_hash(headers, delim)
    )
    assert loaded is not None
    assert loaded["id"] == pid


def test_rollback_removes_batch_rows(conn) -> None:
    import tempfile

    body = "Buchungsdatum,Begünstigter,Betrag\n2026-03-01,X,-20.00\n"
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "y.csv"
        fp.write_text(body, encoding="utf-8")
        r = import_csv_files(conn, "u1", "acc1", [fp])[0]
        assert r.batch_id
        n = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE import_batch_id=?",
            (r.batch_id,),
        ).fetchone()[0]
        assert n == 1
        ok, _ = rollback_import_batch(conn, "u1", "acc1", r.batch_id)
        assert ok
        n2 = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE import_batch_id=?",
            (r.batch_id,),
        ).fetchone()[0]
        assert n2 == 0


def test_preview_csv_file(tmp_path: Path) -> None:
    fp = tmp_path / "p.csv"
    fp.write_text(
        "Buchungsdatum,Begünstigter,Betrag\n2026-01-01,Coop,-1.00\n",
        encoding="utf-8",
    )
    prev = preview_csv_file(fp)
    assert prev["headers"][0] == "Buchungsdatum"
    assert isinstance(prev["detection"], ResolvedColumnMapping)


# ── New tests for UBS MasterCard format ────────────────────────────────────────


def test_strip_sep_hint_removes_excel_metadata() -> None:
    """strip_sep_hint removes leading 'sep=;' rows, not data rows."""
    text = "sep=;\nA;B;C\n1;2;3\n"
    clean, skipped = strip_sep_hint(text)
    assert skipped == 1
    assert clean.startswith("A;B;C")

    text_no_hint = "A;B;C\n1;2;3\n"
    clean2, skipped2 = strip_sep_hint(text_no_hint)
    assert skipped2 == 0
    assert clean2 == text_no_hint


def test_parse_header_row_skips_sep_hint() -> None:
    """parse_header_row must skip Excel sep=; lines and return real headers."""
    raw = "sep=;\nPurchase date;Booking text;Amount;Currency\n20.06.2026;Coop;-55.00;CHF\n".encode("utf-8")
    headers, enc, delim, hdr_idx = parse_header_row(raw)
    assert "Purchase date" in headers
    assert "Booking text" in headers
    assert "sep=;" not in headers
    assert delim == ";"
    assert hdr_idx == 1  # header is on line 1 (after sep=;)


def test_find_header_row_index_multi_metadata() -> None:
    """find_header_row_index locates the real header even after multiple metadata rows."""
    text = (
        "sep=;\n"
        "Konto Nr.: 123-456789.01A\n"
        "Kontoinhaber: Max Mustermann\n"
        "Von: 01.01.2026\n"
        "Bis: 30.06.2026\n"
        "Buchungsdatum;Beschreibung;Betrag;Saldo\n"
        "01.06.2026;Migros;-50.00;4500.00\n"
    )
    idx = find_header_row_index(text, ";")
    assert idx == 5  # "Buchungsdatum;Beschreibung;Betrag;Saldo" is on line 5


def test_find_header_row_index_french_bank() -> None:
    """find_header_row_index works for French-language banks (BCGE-style)."""
    text = (
        "Numero de compte;123456789\n"
        "Titulaire;Jean Dupont\n"
        "Periode;01/01/2026 - 30/06/2026\n"
        "Date;Libelle;Debit;Credit;Solde\n"
        "20.06.2026;Migros;50.00;;1200.00\n"
    )
    idx = find_header_row_index(text, ";")
    assert idx == 3  # "Date;Libelle;Debit;Credit;Solde" is on line 3


def test_import_multi_metadata_rows(conn, tmp_path: Path) -> None:
    """End-to-end: file with 4 metadata rows before the header imports correctly."""
    csv_content = (
        "sep=;\n"
        "Konto Nr.: 123-456789.01A\n"
        "Kontoinhaber: Max Mustermann\n"
        "Von: 01.01.2026\n"
        "Bis: 30.06.2026\n"
        "Buchungsdatum;Buchungstext;Betrag\n"
        "01.06.2026;Migros;-50.00\n"
        "02.06.2026;Coop;-30.00\n"
    )
    fp = tmp_path / "ubs_checking.csv"
    fp.write_bytes(csv_content.encode("utf-8"))

    results = import_csv_files(conn, "u1", "acc1", [fp])
    r = results[0]
    assert not r.skipped, f"Import was skipped: {r.message}"
    assert r.rows_inserted == 2, f"Expected 2 rows, got {r.rows_inserted}. Warnings: {r.warnings}"


def test_detect_mapping_ubs_mastercard() -> None:
    """UBS MasterCard: Amount chosen over empty Debit/Credit; Booked wins as date column."""
    headers = [
        "Account number", "Card number", "Account/Cardholder",
        "Purchase date", "Booking text", "Sector",
        "Amount", "Original currency", "Rate", "Currency",
        "Debit", "Credit", "Booked",
    ]
    # All-pending rows: Debit/Credit empty, Amount filled.
    sample_rows = [
        {"Purchase date": "20.06.2026", "Booking text": "Coop", "Amount": "55.62",
         "Currency": "CHF", "Debit": "", "Credit": "", "Booked": ""},
        {"Purchase date": "19.06.2026", "Booking text": "Migros", "Amount": "31.50",
         "Currency": "CHF", "Debit": "", "Credit": "", "Booked": ""},
    ]
    det = detect_mapping(headers, encoding="utf-8", delimiter=";", sample_rows=sample_rows)
    assert isinstance(det, ResolvedColumnMapping), f"Expected mapping, got: {det}"
    # Debit/Credit empty → Amount chosen; all positive → flipped.
    assert det.sign_rule == "single_amount_flipped", f"Expected single_amount_flipped, got {det.sign_rule}"
    # "Booked" scores 0.97 vs "Purchase date" 0.95 → Booked wins as date column.
    assert det.column_map["date"] == "Booked"
    assert det.column_map["merchant"] == "Booking text"
    assert det.column_map["amount"] == "Amount"


def test_import_ubs_mastercard_format(conn, tmp_path: Path) -> None:
    """End-to-end: UBS MasterCard CSV (positive charges, mixed original currencies) imports correctly.

    Charges must land as negative amounts (outflows).
    'Booked' is the date column — rows without a Booked date are treated as pending and skipped.
    Foreign-currency rows must not be skipped (Amount is CHF-billed when Debit/Credit are empty).
    """
    csv_content = (
        "sep=;\n"
        "Account number;Card number;Account/Cardholder;Purchase date;Booking text;"
        "Sector;Amount;Original currency;Rate;Currency;Debit;Credit;Booked\n"
        # CHF charge with booking date
        "1234;5678;TEST USER;20.06.2026;Coop Lausanne;Grocery stores;55.62;CHF;;CHF;;;21.06.2026\n"
        # USD charge — Amount is the CHF-billed amount (no Debit); must NOT be skipped
        "1234;5678;TEST USER;19.06.2026;Apple App Store;Digital;4.59;USD;0.91;CHF;;;20.06.2026\n"
        # Another CHF charge
        "1234;5678;TEST USER;18.06.2026;SBB;Transport;12.00;CHF;;CHF;;;19.06.2026\n"
        # Pending row (no Booked date) — must be skipped
        "1234;5678;TEST USER;20.06.2026;Pending charge;Misc;9.99;CHF;;CHF;;;\n"
    )
    fp = tmp_path / "UBS_test.csv"
    fp.write_bytes(csv_content.encode("utf-8"))

    results = import_csv_files(conn, "u1", "acc1", [fp])
    r = results[0]
    assert not r.skipped, f"Import was skipped: {r.message}"
    assert r.rows_inserted == 3, (
        f"Expected 3 booked rows, got {r.rows_inserted}. "
        f"Invalid: {r.rows_skipped_invalid}, warnings: {r.warnings}"
    )
    # Pending row has no Booked date → skipped as invalid
    assert r.rows_skipped_invalid == 1, (
        f"Expected 1 pending row skipped, got {r.rows_skipped_invalid}"
    )

    # Charges must be stored as negative outflows
    amounts = [
        row[0] for row in conn.execute(
            "SELECT amount FROM transactions WHERE account_id='acc1' ORDER BY ts"
        ).fetchall()
    ]
    assert all(a < 0 for a in amounts), f"Expected all negative amounts, got {amounts}"
    assert round(sum(amounts), 2) == round(-(55.62 + 4.59 + 12.00), 2)


# ── Sub-plan 1: schema migration column tests ──────────────────────────────────


def test_transactions_has_clean_name_column(conn) -> None:
    """transactions.clean_name column must exist after init_db()."""
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(transactions)").fetchall()
    }
    assert "clean_name" in cols, f"clean_name missing from transactions; got: {cols}"


def test_csv_mapping_profiles_has_etl_memory_columns(conn) -> None:
    """csv_mapping_profiles must have source_label, confirmed, use_count after init_db()."""
    cols = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(csv_mapping_profiles)"
        ).fetchall()
    }
    for col in ("source_label", "confirmed", "use_count"):
        assert col in cols, (
            f"Column '{col}' missing from csv_mapping_profiles; got: {cols}"
        )


def test_merchant_category_overrides_has_labeller_memory_columns(conn) -> None:
    """merchant_category_overrides must have canonical_name, source, confidence,
    override_count after init_db()."""
    cols = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(merchant_category_overrides)"
        ).fetchall()
    }
    for col in ("canonical_name", "source", "confidence", "override_count"):
        assert col in cols, (
            f"Column '{col}' missing from merchant_category_overrides; got: {cols}"
        )


def test_migrate_schema_idempotent(tmp_path: Path) -> None:
    """Running migrate_schema() twice on the same DB must not raise."""
    from db.db_schema import migrate_schema

    dbp = tmp_path / "idem.db"
    c = init_db(str(dbp))
    # Second call must be safe (no duplicate ALTER TABLE errors)
    migrate_schema(c)
    c.commit()


def test_migrate_schema_on_old_db_missing_new_columns(tmp_path: Path) -> None:
    """migrate_schema() must add new columns to a DB that was created without them."""
    import sqlite3 as _sqlite3
    from db.db_schema import migrate_schema

    dbp = tmp_path / "old.db"
    c = _sqlite3.connect(str(dbp))
    # Minimal old schema — only the tables, without the new columns
    c.executescript(
        """
        CREATE TABLE users (id TEXT PRIMARY KEY, display_name TEXT, created_at TEXT);
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY, user_id TEXT, name TEXT,
            balance REAL, currency TEXT
        );
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY, account_id TEXT, amount REAL,
            currency TEXT DEFAULT 'CHF', merchant TEXT,
            category TEXT, ts TEXT
        );
        CREATE TABLE csv_mapping_profiles (
            id TEXT PRIMARY KEY, user_id TEXT, display_name TEXT,
            column_map TEXT, sign_rule TEXT, encoding TEXT,
            delimiter TEXT, header_hash TEXT, is_default INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE merchant_category_overrides (
            id TEXT PRIMARY KEY, user_id TEXT, merchant_normalized TEXT,
            bucket TEXT, line_category TEXT, updated_at TEXT,
            UNIQUE(user_id, merchant_normalized)
        );
        CREATE TABLE goals (id TEXT PRIMARY KEY, user_id TEXT, goal_type TEXT,
            engagement TEXT, active INTEGER, created_at TEXT);
        CREATE TABLE budgets (id TEXT PRIMARY KEY, user_id TEXT,
            allocations TEXT, target_ratios TEXT, period TEXT, created_at TEXT);
        CREATE TABLE prefs (user_id TEXT PRIMARY KEY);
        CREATE TABLE import_batches (id TEXT PRIMARY KEY, user_id TEXT,
            source_path TEXT, content_sha256 TEXT, imported_at TEXT,
            row_count INTEGER DEFAULT 0, skipped_duplicate_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'completed');
        CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT, started_at TEXT);
        CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT,
            role TEXT, content TEXT, ts TEXT);
        CREATE TABLE conversation_summary (user_id TEXT PRIMARY KEY,
            summary TEXT, updated_at TEXT);
        CREATE TABLE learned_preferences (id TEXT PRIMARY KEY, user_id TEXT,
            kind TEXT, subject TEXT, value TEXT,
            suppressible INTEGER DEFAULT 1, evidence_count INTEGER DEFAULT 1,
            updated_at TEXT);
        CREATE TABLE split_snapshots (id TEXT PRIMARY KEY, user_id TEXT,
            period TEXT, needs_pct REAL, wants_pct REAL, savings_pct REAL,
            taken_at TEXT);
        CREATE TABLE pending_notifications (id TEXT PRIMARY KEY, user_id TEXT,
            tier TEXT, summary TEXT, offered_actions TEXT,
            status TEXT DEFAULT 'awaiting', created_at TEXT);
        CREATE TABLE category_proposals (id TEXT PRIMARY KEY, user_id TEXT,
            txn_id TEXT, proposed_bucket TEXT, proposed_line TEXT,
            rationale TEXT, status TEXT DEFAULT 'pending', created_at TEXT);
        """
    )
    c.commit()

    migrate_schema(c)
    c.commit()

    # All new columns must now exist
    txn_cols = {row[1] for row in c.execute("PRAGMA table_info(transactions)")}
    assert "clean_name" in txn_cols

    prof_cols = {
        row[1] for row in c.execute("PRAGMA table_info(csv_mapping_profiles)")
    }
    for col in ("source_label", "confirmed", "use_count"):
        assert col in prof_cols, f"Missing '{col}' after migration"

    mco_cols = {
        row[1]
        for row in c.execute("PRAGMA table_info(merchant_category_overrides)")
    }
    for col in ("canonical_name", "source", "confidence", "override_count"):
        assert col in mco_cols, f"Missing '{col}' after migration"


# ── Tests for mixed Debit/Credit detection (booked + pending rows) ─────────────


def test_detect_mapping_ubs_mastercard_mixed_debit() -> None:
    """When some sample rows have Debit filled and some don't (pending), prefer debit_credit."""
    headers = [
        "Account number", "Card number", "Account/Cardholder",
        "Purchase date", "Booking text", "Sector",
        "Amount", "Original currency", "Rate", "Currency",
        "Debit", "Credit", "Booked",
    ]
    sample_rows = [
        # Pending — Debit/Credit/Booked empty, Amount filled
        {"Purchase date": "20.06.2026", "Booking text": "Coop", "Amount": "55.62",
         "Currency": "CHF", "Debit": "", "Credit": "", "Booked": ""},
        {"Purchase date": "19.06.2026", "Booking text": "Migros", "Amount": "31.50",
         "Currency": "CHF", "Debit": "", "Credit": "", "Booked": ""},
        # Booked — Debit has CHF amount, Booked has settlement date
        {"Purchase date": "15.06.2026", "Booking text": "Starbucks", "Amount": "6.50",
         "Currency": "CHF", "Debit": "6.50", "Credit": "", "Booked": "16.06.2026"},
        {"Purchase date": "14.06.2026", "Booking text": "Apple", "Amount": "21.62",
         "Currency": "USD", "Debit": "17.86", "Credit": "", "Booked": "16.06.2026"},
        {"Purchase date": "13.06.2026", "Booking text": "SBB", "Amount": "55.00",
         "Currency": "CHF", "Debit": "55.00", "Credit": "", "Booked": "14.06.2026"},
    ]
    det = detect_mapping(headers, encoding="utf-8", delimiter=";", sample_rows=sample_rows)
    assert isinstance(det, ResolvedColumnMapping), f"Expected mapping, got: {det}"
    assert det.sign_rule == "debit_credit", (
        f"Expected debit_credit (booked rows present), got {det.sign_rule}"
    )
    assert det.column_map["debit"] == "Debit"
    # "Booked" (0.97) beats "Purchase date" (0.95) as the date column.
    assert det.column_map["date"] == "Booked"
    assert det.column_map["merchant"] == "Booking text"


def test_import_ubs_mastercard_booked_rows(conn, tmp_path: Path) -> None:
    """End-to-end: mix of booked (Debit filled) and pending rows.

    Booked rows use the Debit column for the CHF amount.
    Pending rows (empty Debit + Credit) are skipped with a warning.
    Foreign-currency rows import using the Debit (CHF) amount, not the local Amount.
    """
    csv_content = (
        "sep=;\n"
        "Account number;Card number;Account/Cardholder;Purchase date;Booking text;"
        "Sector;Amount;Original currency;Rate;Currency;Debit;Credit;Booked\n"
        # 2 pending (Debit/Credit/Booked empty) — must be skipped
        "1234;5678;TEST;20.06.2026;Coop;Grocery;55.62;CHF;;CHF;;;\n"
        "1234;5678;TEST;19.06.2026;Migros;Grocery;31.50;CHF;;CHF;;;\n"
        # 3 booked: CHF, USD (Debit = CHF-billed), and a Credit (refund) — all have Booked date
        "1234;5678;TEST;15.06.2026;Starbucks;Coffee;6.50;CHF;;CHF;6.50;;16.06.2026\n"
        "1234;5678;TEST;14.06.2026;Apple Store;Digital;21.62;USD;0.826;CHF;17.86;;16.06.2026\n"
        "1234;5678;TEST;10.06.2026;Refund Shop;Misc;50.00;CHF;;CHF;;50.00;11.06.2026\n"
    )
    fp = tmp_path / "UBS_mixed.csv"
    fp.write_bytes(csv_content.encode("utf-8"))

    results = import_csv_files(conn, "u1", "acc1", [fp])
    r = results[0]
    assert not r.skipped, f"Import was skipped: {r.message}"
    assert r.rows_inserted == 3, (
        f"Expected 3 booked rows, got {r.rows_inserted}. "
        f"Invalid: {r.rows_skipped_invalid}, warnings: {r.warnings}"
    )
    assert r.rows_skipped_invalid == 2, (
        f"Expected 2 pending rows skipped, got {r.rows_skipped_invalid}"
    )

    # Verify a warning about pending rows was emitted
    pending_warns = [w for w in r.warnings if "pending" in w.lower()]
    assert pending_warns, f"Expected pending-row warning, got: {r.warnings}"

    amounts = sorted(
        row[0] for row in conn.execute(
            "SELECT amount FROM transactions WHERE account_id='acc1'"
        ).fetchall()
    )
    # Starbucks: -6.50, Apple (CHF-billed): -17.86, Refund: +50.00
    assert round(amounts[0], 2) == -17.86, f"Apple CHF-billed amount wrong: {amounts}"
    assert round(amounts[1], 2) == -6.50, f"Starbucks amount wrong: {amounts}"
    assert round(amounts[2], 2) == 50.00, f"Refund amount wrong: {amounts}"

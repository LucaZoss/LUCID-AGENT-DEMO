"""Tests for CSV header detection, import dedupe, profiles, and rollback."""

from __future__ import annotations

from pathlib import Path

import pytest

from db.db_schema import init_db
from ingest.csv_detect import ResolvedColumnMapping, detect_mapping, header_row_hash, parse_header_row
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
    headers, enc, delim = parse_header_row(raw)
    assert "Buchungsdatum" in headers
    assert delim == ";"
    assert enc.startswith("utf-8")


def test_detect_mapping_single_amount() -> None:
    raw = (
        "Buchungsdatum,Begünstigter,Betrag\n"
        "2026-01-01,Coop,-10.00\n"
    ).encode("utf-8")
    headers, enc, delim = parse_header_row(raw)
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
    headers, enc, delim = parse_header_row(raw)
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

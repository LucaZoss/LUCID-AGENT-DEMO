"""Tests for tools/etl/ — complexity_analyzer, normalizer, column_mapper."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from tools.etl.complexity_analyzer import analyze_complexity
from tools.etl.column_mapper import header_fingerprint, heuristic_map
from tools.etl.normalizer import normalize_dataframe


# ── complexity_analyzer ────────────────────────────────────────────────────────


def test_analyze_complexity_csv(tmp_path: Path) -> None:
    fp = tmp_path / "sample.csv"
    fp.write_text("Buchungsdatum;Betrag;Begünstigter\n2026-01-01;-10.00;Coop\n", encoding="utf-8")
    result = analyze_complexity(str(fp))
    assert result.strategy == "pandas"
    assert not result.is_complex
    assert result.stats["approx_line_count"] >= 1


def test_analyze_complexity_missing_file() -> None:
    result = analyze_complexity("/nonexistent/path/file.csv")
    assert "error" in result.stats


# ── column_mapper ──────────────────────────────────────────────────────────────


def test_header_fingerprint_stable() -> None:
    h1 = header_fingerprint(["Date", "Amount", "Merchant"])
    h2 = header_fingerprint(["Date", "Amount", "Merchant"])
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_header_fingerprint_order_independent() -> None:
    h1 = header_fingerprint(["Date", "Amount", "Merchant"])
    h2 = header_fingerprint(["Amount", "Merchant", "Date"])
    assert h1 == h2


def test_heuristic_map_standard_headers() -> None:
    headers = ["Buchungsdatum", "Begünstigter", "Betrag"]
    result = heuristic_map(headers)
    assert not result["ambiguous"]
    assert result["column_map"]["date"] == "Buchungsdatum"
    assert result["column_map"]["merchant"] == "Begünstigter"
    assert result["column_map"]["amount"] == "Betrag"
    assert len(result["header_fingerprint"]) == 64


def test_heuristic_map_empty_headers() -> None:
    result = heuristic_map([])
    assert result["ambiguous"]


# ── normalizer ─────────────────────────────────────────────────────────────────


def test_normalize_dataframe_basic() -> None:
    df = pd.DataFrame([
        {"Buchungsdatum": "2026-01-15", "Begünstigter": "Coop", "Betrag": "-42.50"},
        {"Buchungsdatum": "2026-01-16", "Begünstigter": "Migros", "Betrag": "-18.00"},
    ])
    column_map = {"date": "Buchungsdatum", "merchant": "Begünstigter", "amount": "Betrag"}
    result = normalize_dataframe(df, column_map, "single_amount")
    assert len(result) == 2
    assert list(result.columns) == ["date", "merchant", "amount", "currency"]
    assert result.iloc[0]["amount"] == -42.50
    assert result.iloc[0]["merchant"] == "Coop"


def test_normalize_dataframe_drops_invalid_dates() -> None:
    df = pd.DataFrame([
        {"date": "not-a-date", "merchant": "Coop", "amount": "-10.00"},
        {"date": "2026-03-01", "merchant": "Migros", "amount": "-5.00"},
    ])
    column_map = {"date": "date", "merchant": "merchant", "amount": "amount"}
    result = normalize_dataframe(df, column_map, "single_amount")
    assert len(result) == 1
    assert result.iloc[0]["merchant"] == "Migros"


def test_normalize_dataframe_drops_zero_amounts() -> None:
    df = pd.DataFrame([
        {"date": "2026-01-01", "merchant": "A", "amount": "0.00"},
        {"date": "2026-01-02", "merchant": "B", "amount": "-5.00"},
    ])
    column_map = {"date": "date", "merchant": "merchant", "amount": "amount"}
    result = normalize_dataframe(df, column_map, "single_amount")
    assert len(result) == 1


def test_normalize_dataframe_debit_credit() -> None:
    df = pd.DataFrame([
        {"Datum": "2026-02-10", "Beschreibung": "SBB", "Belastung": "55.00", "Gutschrift": ""},
        {"Datum": "2026-02-11", "Beschreibung": "Salary", "Belastung": "", "Gutschrift": "5000.00"},
    ])
    column_map = {
        "date": "Datum",
        "merchant": "Beschreibung",
        "debit": "Belastung",
        "credit": "Gutschrift",
    }
    result = normalize_dataframe(df, column_map, "debit_credit")
    assert len(result) == 2
    sbb = result[result["merchant"] == "SBB"].iloc[0]
    salary = result[result["merchant"] == "Salary"].iloc[0]
    assert sbb["amount"] == -55.00
    assert salary["amount"] == 5000.00


def test_normalize_dataframe_against_real_csv() -> None:
    """Smoke test: normalize the actual Mastercard CSV in data/imports/."""
    csv_path = Path(__file__).parent.parent / "data" / "imports" / "UBS_MasterCard_YTD.csv"
    if not csv_path.is_file():
        pytest.skip("Real Mastercard CSV not present")

    import pandas as _pd
    from ingest.csv_detect import parse_header_row, detect_mapping
    from ingest.importer import _rows_from_csv

    raw = csv_path.read_bytes()
    headers, enc, delim, hdr_idx = parse_header_row(raw)
    _, data_rows = _rows_from_csv(raw, enc, delim, hdr_idx)
    sample = data_rows[:20]

    mapping = detect_mapping(headers, encoding=enc, delimiter=delim, sample_rows=sample)
    from ingest.csv_detect import ResolvedColumnMapping
    assert isinstance(mapping, ResolvedColumnMapping), f"Detection failed: {mapping}"

    df = _pd.DataFrame(data_rows)
    result = normalize_dataframe(df, mapping.column_map, mapping.sign_rule)
    # At least some rows should survive normalization
    assert len(result) > 0

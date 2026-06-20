"""Tests for the LLM-based CSV column mapping fallback (agents/csv_mapper.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.csv_mapper import resolve_mapping_with_llm
from ingest.csv_detect import LucidField, MappingAmbiguity, ResolvedColumnMapping
from llm.provider import LLMResponse


def _mock_llm(content: str):
    """Return a mock LLMProvider that responds with *content*."""
    llm = MagicMock()
    llm.complete.return_value = LLMResponse(
        content=content, tool_calls=[], stop_reason="end_turn"
    )
    return llm


def _make_preview(
    headers: list[str],
    sample_rows: list[dict] | None = None,
    missing: list[str] | None = None,
) -> dict:
    """Build a minimal preview dict that matches preview_csv_file() output."""
    ambiguity = MappingAmbiguity(
        message="missing: " + ", ".join(missing or ["merchant"]),
        missing_required=missing or ["merchant"],
        tied_fields={},
        best_effort={},
    )
    return {
        "headers": headers,
        "encoding": "utf-8",
        "delimiter": ";",
        "detection": ambiguity,
        "sample_rows": sample_rows or [],
    }


# ── happy paths ───────────────────────────────────────────────────────────────

def test_resolve_mapping_single_amount():
    """LLM returns valid JSON for a single-amount CSV → ResolvedColumnMapping."""
    headers = ["Datum", "Betrag", "Buchungstext"]
    preview = _make_preview(headers)
    payload = {
        "date_col": "Datum",
        "amount_col": "Betrag",
        "merchant_col": "Buchungstext",
        "debit_col": None,
        "credit_col": None,
        "currency_col": None,
        "sign_rule": "single_amount",
    }
    llm = _mock_llm(json.dumps(payload))
    result = resolve_mapping_with_llm(llm, preview)

    assert isinstance(result, ResolvedColumnMapping)
    assert result.column_map[LucidField.DATE.value] == "Datum"
    assert result.column_map[LucidField.MERCHANT.value] == "Buchungstext"
    assert result.column_map[LucidField.AMOUNT.value] == "Betrag"
    assert result.sign_rule == "single_amount"
    assert result.encoding == "utf-8"
    assert result.delimiter == ";"


def test_resolve_mapping_debit_credit():
    """Debit/credit sign rule maps both columns correctly."""
    headers = ["Date", "Description", "Debit", "Credit"]
    preview = _make_preview(headers)
    payload = {
        "date_col": "Date",
        "amount_col": None,
        "merchant_col": "Description",
        "debit_col": "Debit",
        "credit_col": "Credit",
        "currency_col": None,
        "sign_rule": "debit_credit",
    }
    llm = _mock_llm(json.dumps(payload))
    result = resolve_mapping_with_llm(llm, preview)

    assert result.sign_rule == "debit_credit"
    assert result.column_map.get(LucidField.DEBIT.value) == "Debit"
    assert result.column_map.get(LucidField.CREDIT.value) == "Credit"


def test_resolve_mapping_optional_currency():
    """Optional currency column is mapped when LLM provides it."""
    headers = ["Date", "Merchant", "Amount", "CCY"]
    preview = _make_preview(headers)
    payload = {
        "date_col": "Date",
        "amount_col": "Amount",
        "merchant_col": "Merchant",
        "debit_col": None,
        "credit_col": None,
        "currency_col": "CCY",
        "sign_rule": "single_amount",
    }
    llm = _mock_llm(json.dumps(payload))
    result = resolve_mapping_with_llm(llm, preview)
    assert result.column_map.get(LucidField.CURRENCY.value) == "CCY"


def test_resolve_mapping_strips_markdown_code_fences():
    """LLM wraps response in ```json ... ``` — should still parse."""
    headers = ["Date", "Merchant", "Amount"]
    preview = _make_preview(headers)
    inner = json.dumps({
        "date_col": "Date",
        "amount_col": "Amount",
        "merchant_col": "Merchant",
        "debit_col": None,
        "credit_col": None,
        "currency_col": None,
        "sign_rule": "single_amount",
    })
    llm = _mock_llm(f"```json\n{inner}\n```")
    result = resolve_mapping_with_llm(llm, preview)
    assert result.column_map[LucidField.DATE.value] == "Date"


# ── error paths ───────────────────────────────────────────────────────────────

def test_resolve_mapping_unknown_column_raises():
    """LLM returns a column name not present in the headers → ValueError."""
    headers = ["Date", "Merchant", "Amount"]
    preview = _make_preview(headers)
    payload = {
        "date_col": "Date",
        "merchant_col": "DescriptionXYZ",  # not in headers
        "amount_col": "Amount",
        "debit_col": None,
        "credit_col": None,
        "currency_col": None,
        "sign_rule": "single_amount",
    }
    llm = _mock_llm(json.dumps(payload))
    with pytest.raises(ValueError, match="unknown column"):
        resolve_mapping_with_llm(llm, preview)


def test_resolve_mapping_non_json_raises():
    """LLM returns prose instead of JSON → ValueError."""
    preview = _make_preview(["Date", "Merchant", "Amount"])
    llm = _mock_llm("Sorry, I cannot determine the column mapping.")
    with pytest.raises(ValueError, match="non-JSON"):
        resolve_mapping_with_llm(llm, preview)


def test_resolve_mapping_missing_date_raises():
    """LLM omits required date_col → ValueError."""
    headers = ["Date", "Merchant", "Amount"]
    preview = _make_preview(headers)
    payload = {
        "date_col": None,  # missing required
        "merchant_col": "Merchant",
        "amount_col": "Amount",
        "debit_col": None,
        "credit_col": None,
        "currency_col": None,
        "sign_rule": "single_amount",
    }
    llm = _mock_llm(json.dumps(payload))
    with pytest.raises(ValueError, match="missing required"):
        resolve_mapping_with_llm(llm, preview)


def test_resolve_mapping_missing_merchant_raises():
    """LLM omits required merchant_col → ValueError."""
    headers = ["Date", "Merchant", "Amount"]
    preview = _make_preview(headers)
    payload = {
        "date_col": "Date",
        "merchant_col": None,  # missing required
        "amount_col": "Amount",
        "debit_col": None,
        "credit_col": None,
        "currency_col": None,
        "sign_rule": "single_amount",
    }
    llm = _mock_llm(json.dumps(payload))
    with pytest.raises(ValueError, match="missing required"):
        resolve_mapping_with_llm(llm, preview)


def test_resolve_mapping_invalid_sign_rule_defaults_to_single():
    """Unknown sign_rule defaults to single_amount rather than raising."""
    headers = ["Date", "Merchant", "Amount"]
    preview = _make_preview(headers)
    payload = {
        "date_col": "Date",
        "merchant_col": "Merchant",
        "amount_col": "Amount",
        "debit_col": None,
        "credit_col": None,
        "currency_col": None,
        "sign_rule": "weird_rule",
    }
    llm = _mock_llm(json.dumps(payload))
    result = resolve_mapping_with_llm(llm, preview)
    assert result.sign_rule == "single_amount"

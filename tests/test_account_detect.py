"""Tests for account type heuristic in ingest/account_detect.py."""

from __future__ import annotations

import pytest

from ingest.account_detect import AccountProposal, propose_account_heuristic
from ingest.csv_detect import ResolvedColumnMapping


def _preview(sign_rule: str, sample_amounts: list[float]) -> dict:
    """Build a minimal preview dict for testing."""
    col_map = {"date": "Date", "merchant": "Desc"}
    if sign_rule in ("single_amount", "single_amount_flipped"):
        col_map["amount"] = "Amount"
    else:
        col_map["debit"] = "Debit"
        col_map["credit"] = "Credit"
    det = ResolvedColumnMapping(
        column_map=col_map, sign_rule=sign_rule, encoding="utf-8", delimiter=","
    )
    sample_rows = [{"Amount": str(a), "Desc": "Merchant", "Date": "2026-01-01"} for a in sample_amounts]
    return {"detection": det, "sample_rows": sample_rows, "headers": list(col_map.values())}


def test_credit_card_from_sign_rule():
    """single_amount_flipped → credit_card, no income, high confidence."""
    p = propose_account_heuristic(_preview("single_amount_flipped", [10.0, 25.0, 5.0]), "visa_export.csv")
    assert p.account_type == "credit_card"
    assert p.has_income is False
    assert p.confidence == "high"


def test_credit_card_all_non_negative():
    """All-positive amounts (outflow convention) → credit_card even without sign_rule flip."""
    p = propose_account_heuristic(_preview("single_amount", [10.0, 25.0, 5.0, 0.0]), "card.csv")
    assert p.account_type == "credit_card"
    assert p.has_income is False
    assert p.confidence == "high"


def test_checking_with_income_large_positive():
    """Any amount > 1000 CHF → checking with income, high confidence."""
    p = propose_account_heuristic(_preview("single_amount", [-50.0, -30.0, 4500.0, -20.0]), "ubs_checking.csv")
    assert p.account_type == "checking"
    assert p.has_income is True
    assert p.confidence == "high"


def test_low_confidence_no_large_inflow():
    """Mixed small pos/neg, no large inflow → checking, no income, low confidence."""
    p = propose_account_heuristic(_preview("single_amount", [-50.0, -30.0, 5.0, -20.0]), "unknown.csv")
    assert p.account_type == "checking"
    assert p.has_income is False
    assert p.confidence == "low"


def test_empty_samples_low_confidence():
    """No sample rows → low confidence checking."""
    p = propose_account_heuristic(
        {"detection": ResolvedColumnMapping({"date": "D", "merchant": "M", "amount": "A"}, "single_amount", "utf-8", ","),
         "sample_rows": [], "headers": ["D", "M", "A"]},
        "empty.csv"
    )
    assert p.account_type == "checking"
    assert p.confidence == "low"


def test_name_from_filename():
    """Filename stem is converted to a readable display name."""
    p = propose_account_heuristic(_preview("single_amount_flipped", [5.0]), "ubs_credit_card_2026.csv")
    assert "Ubs" in p.name or "UBS" in p.name.upper()

"""Tests for tools/labeller/bucket_classifier.py — classify_bucket."""

from __future__ import annotations

import pytest

from contracts import Transaction
from tools.labeller.bucket_classifier import classify_bucket


def _txn(merchant: str, amount: float = -10.0) -> Transaction:
    return Transaction(
        id="test-1",
        account_id="acc1",
        amount=amount,
        currency="CHF",
        merchant=merchant,
        category=None,
        ts="2026-01-01T00:00:00+00:00",
    )


# ── sector hint override ───────────────────────────────────────────────────────

def test_sector_hint_grocery_stores() -> None:
    bucket, confidence = classify_bucket(_txn("Unknown Shop"), sector_hint="Grocery stores")
    assert bucket == "need"
    assert confidence == 0.85


def test_sector_hint_restaurants() -> None:
    bucket, confidence = classify_bucket(_txn("Mystery Diner"), sector_hint="Restaurants")
    assert bucket == "want"
    assert confidence == 0.85


def test_sector_hint_investment() -> None:
    bucket, confidence = classify_bucket(_txn("XYZ Fund"), sector_hint="Investment")
    assert bucket == "savings"
    assert confidence == 0.85


def test_sector_hint_case_insensitive() -> None:
    bucket, _ = classify_bucket(_txn("X"), sector_hint="GROCERY STORES")
    assert bucket == "need"


# ── deterministic rule fallback ───────────────────────────────────────────────

def test_known_merchant_coop() -> None:
    bucket, confidence = classify_bucket(_txn("Coop"))
    assert bucket == "need"
    assert confidence == 0.9


def test_known_merchant_netflix() -> None:
    bucket, confidence = classify_bucket(_txn("Netflix"))
    assert bucket == "want"
    assert confidence == 0.9


def test_known_merchant_viac() -> None:
    bucket, confidence = classify_bucket(_txn("VIAC 3a"))
    assert bucket == "savings"
    assert confidence == 0.9


def test_unknown_merchant_defaults_want_low_confidence() -> None:
    bucket, confidence = classify_bucket(_txn("Random Corp XYZ 123"))
    assert bucket == "want"
    assert confidence == 0.5


def test_sector_hint_unknown_falls_through_to_rules() -> None:
    # Sector not in map → fall through to rule-based
    bucket, _ = classify_bucket(_txn("Coop"), sector_hint="Misc")
    assert bucket == "need"


def test_no_sector_hint_uses_rules() -> None:
    bucket, confidence = classify_bucket(_txn("Migros"))
    assert bucket == "need"
    assert confidence == 0.9

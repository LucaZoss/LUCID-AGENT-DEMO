"""Tests for tools/labeller/name_cleaner.py — clean_merchant_name."""

from __future__ import annotations

import pytest

from tools.labeller.name_cleaner import clean_merchant_name


@pytest.mark.parametrize("raw,expected", [
    # Trailing location + country
    ("UPTRACK+                 RENNES       FRA", "Uptrack+"),
    ("COOP BERN                BERN         CHE", "Coop Bern"),
    ("MIGROS ONLINE            ZURICH       CHE", "Migros Online"),
    # Already clean
    ("Starbucks", "Starbucks"),
    ("SBB", "Sbb"),
    ("Netflix", "Netflix"),
    # Double internal spaces (no trailing location — only 2 spaces, not 5+)
    ("APPLE  APP  STORE", "Apple App Store"),
    # Empty string
    ("", ""),
    # Only whitespace
    ("   ", ""),
])
def test_clean_merchant_name(raw: str, expected: str) -> None:
    assert clean_merchant_name(raw) == expected


def test_clean_merchant_name_preserves_short_merchant() -> None:
    result = clean_merchant_name("Coop")
    assert result == "Coop"


def test_clean_merchant_name_strips_leading_trailing_whitespace() -> None:
    result = clean_merchant_name("  Migros  ")
    assert result == "Migros"

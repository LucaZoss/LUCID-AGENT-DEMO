"""Tests for the canonical category taxonomy and mapping layer."""

from __future__ import annotations

import pytest

from categories import (
    TAXONOMY,
    BY_KEY,
    VALID_KEYS,
    ALL_KEYS_SORTED,
    NormalizedCategory,
    derive_legacy_bucket,
    display_path,
    is_valid_key,
)
from categories_mapping import map_from_line_category, map_from_merchant_key


class TestTaxonomyIntegrity:

    def test_no_duplicate_keys(self):
        keys = [c.key for c in TAXONOMY]
        assert len(keys) == len(set(keys)), "Duplicate keys in TAXONOMY"

    def test_by_key_matches_taxonomy(self):
        for cat in TAXONOMY:
            assert cat.key in BY_KEY
            assert BY_KEY[cat.key] is cat

    def test_valid_keys_matches_by_key(self):
        assert VALID_KEYS == frozenset(BY_KEY.keys())

    def test_all_keys_sorted_is_sorted(self):
        assert ALL_KEYS_SORTED == sorted(ALL_KEYS_SORTED)

    def test_all_groups_present(self):
        groups = {c.group for c in TAXONOMY}
        assert groups == {"Needs", "Wants", "Income", "Extras"}

    def test_all_top_types_present(self):
        types = {c.top_type for c in TAXONOMY}
        assert types == {"Expenses", "Income", "Extras"}

    def test_expected_keys_present(self):
        for key in [
            "rent", "health_insurance", "groceries_food", "telecom",
            "car", "clothing", "digital_goods", "health_other", "housing",
            "restaurants", "sports", "travel_holidays", "transport",
            "wellbeing", "wants_other",
            "salary",
            "twint_credit", "twint_debit", "extras_other",
        ]:
            assert key in VALID_KEYS, f"Expected key {key!r} missing from taxonomy"

    def test_count_is_19(self):
        assert len(TAXONOMY) == 19


class TestDeriveLegacyBucket:

    def test_needs_map_to_need(self):
        for key in ["rent", "health_insurance", "groceries_food", "telecom"]:
            assert derive_legacy_bucket(key) == "need", key

    def test_wants_map_to_want(self):
        for key in ["car", "clothing", "digital_goods", "health_other",
                    "housing", "restaurants", "sports", "travel_holidays",
                    "transport", "wellbeing", "wants_other"]:
            assert derive_legacy_bucket(key) == "want", key

    def test_income_returns_none(self):
        assert derive_legacy_bucket("salary") is None

    def test_extras_return_none(self):
        for key in ["twint_credit", "twint_debit", "extras_other"]:
            assert derive_legacy_bucket(key) is None, key

    def test_unknown_key_returns_none(self):
        assert derive_legacy_bucket("custom_user_category") is None


class TestIsValidKey:

    def test_valid_keys_return_true(self):
        for key in VALID_KEYS:
            assert is_valid_key(key)

    def test_invalid_key_returns_false(self):
        assert not is_valid_key("luxury_travel")
        assert not is_valid_key("")
        assert not is_valid_key("need")  # legacy bucket, not a taxonomy key


class TestDisplayPath:

    def test_expenses_needs(self):
        assert display_path("rent") == "Expenses / Needs / Rent"

    def test_expenses_wants(self):
        assert display_path("restaurants") == "Expenses / Wants / Restaurants"

    def test_income(self):
        assert display_path("salary") == "Income / Salary"

    def test_extras(self):
        assert display_path("twint_credit") == "Extras / Twint Chargeback (Credit)"

    def test_custom_key_returns_raw(self):
        assert display_path("my_custom_cat") == "my_custom_cat"


class TestMapFromLineCategory:

    def test_known_slugs(self):
        assert map_from_line_category("groceries") == "groceries_food"
        assert map_from_line_category("dining") == "restaurants"
        assert map_from_line_category("telecom") == "telecom"
        assert map_from_line_category("clothing") == "clothing"
        assert map_from_line_category("electronics") == "digital_goods"
        assert map_from_line_category("streaming") == "digital_goods"
        assert map_from_line_category("rent") == "rent"
        assert map_from_line_category("health_insurance") == "health_insurance"
        assert map_from_line_category("salary") == "salary"

    def test_savings_transfer_returns_none(self):
        assert map_from_line_category("savings_transfer") is None

    def test_unknown_returns_none(self):
        assert map_from_line_category("unknown_label_xyz") is None

    def test_none_input_returns_none(self):
        assert map_from_line_category(None) is None

    def test_labeller_human_labels(self):
        assert map_from_line_category("Grocery Stores") == "groceries_food"
        assert map_from_line_category("Streaming Services") == "digital_goods"
        assert map_from_line_category("Clothing & Fashion") == "clothing"


class TestMapFromMerchantKey:

    def test_swiss_grocery_chains(self):
        for merchant in ["migros", "coop superstore", "aldi suisse", "denner"]:
            assert map_from_merchant_key(merchant) == "groceries_food", merchant

    def test_streaming(self):
        for merchant in ["netflix", "spotify", "disney+"]:
            assert map_from_merchant_key(merchant) == "digital_goods", merchant

    def test_restaurants(self):
        for merchant in ["starbucks", "mcdonalds", "pizza"]:
            assert map_from_merchant_key(merchant) == "restaurants", merchant

    def test_transport(self):
        for merchant in ["sbb", "zvv", "bls"]:
            assert map_from_merchant_key(merchant) == "transport", merchant

    def test_telecom(self):
        for merchant in ["swisscom", "sunrise", "salt.ch"]:
            assert map_from_merchant_key(merchant) == "telecom", merchant

    def test_health_insurance(self):
        for merchant in ["helsana", "swica", "css versicherung"]:
            assert map_from_merchant_key(merchant) == "health_insurance", merchant

    def test_unknown_returns_none(self):
        assert map_from_merchant_key("restaurant xyz abc 12345") is None

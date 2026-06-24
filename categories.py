"""
Canonical transaction category taxonomy for the personal finance agent.

Single source of truth for all normalized category keys, display names,
and group membership. Import this module anywhere that needs to classify or
display transactions — never hard-code category strings elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedCategory:
    key: str         # DB slug stored in normalized_category column
    name: str        # Human-readable display label
    group: str       # "Needs" | "Wants" | "Income" | "Extras"
    top_type: str    # "Expenses" | "Income" | "Extras"
    description: str = ""


TAXONOMY: list[NormalizedCategory] = [
    # ── Expenses / Needs ────────────────────────────────────────────────────
    NormalizedCategory("rent",             "Rent",              "Needs",  "Expenses"),
    NormalizedCategory("health_insurance", "Health Insurance",  "Needs",  "Expenses"),
    NormalizedCategory("groceries_food",   "Groceries/Food",    "Needs",  "Expenses"),
    NormalizedCategory("telecom",          "Telecommunication", "Needs",  "Expenses",
                       "Internet and mobile subscriptions"),
    # ── Expenses / Wants ────────────────────────────────────────────────────
    NormalizedCategory("car",              "Car",               "Wants",  "Expenses",
                       "Parking, leasing, gasoline"),
    NormalizedCategory("clothing",         "Clothing",          "Wants",  "Expenses"),
    NormalizedCategory("digital_goods",    "Digital Goods",     "Wants",  "Expenses",
                       "Electronics, tech subscriptions"),
    NormalizedCategory("health_other",     "Health Other",      "Wants",  "Expenses"),
    NormalizedCategory("housing",          "Housing",           "Wants",  "Expenses",
                       "Furniture, home utilities"),
    NormalizedCategory("restaurants",      "Restaurants",       "Wants",  "Expenses"),
    NormalizedCategory("sports",           "Sports",            "Wants",  "Expenses"),
    NormalizedCategory("travel_holidays",  "Travel/Holidays",   "Wants",  "Expenses",
                       "Flights, hotels"),
    NormalizedCategory("transport",        "Transport",         "Wants",  "Expenses",
                       "Trains and public transit"),
    NormalizedCategory("wellbeing",        "Wellbeing",         "Wants",  "Expenses"),
    NormalizedCategory("wants_other",      "Others",            "Wants",  "Expenses"),
    # ── Income ──────────────────────────────────────────────────────────────
    NormalizedCategory("salary",           "Salary",            "Income", "Income"),
    # ── Extras ──────────────────────────────────────────────────────────────
    NormalizedCategory("twint_credit",     "Twint Chargeback (Credit)", "Extras", "Extras"),
    NormalizedCategory("twint_debit",      "Twint Chargeback (Debit)",  "Extras", "Extras"),
    NormalizedCategory("extras_other",     "Others",            "Extras", "Extras"),
]

BY_KEY: dict[str, NormalizedCategory] = {c.key: c for c in TAXONOMY}
VALID_KEYS: frozenset[str] = frozenset(BY_KEY)
ALL_KEYS_SORTED: list[str] = sorted(VALID_KEYS)


def derive_legacy_bucket(key: str) -> str | None:
    """Map a normalized_category key to the legacy need/want/savings bucket.

    Returns None for Income and Extras rows — they do not belong to a
    need/want/savings bucket and should be excluded from NWS compute_split.
    """
    cat = BY_KEY.get(key)
    if cat is None:
        return None
    if cat.group == "Needs":
        return "need"
    if cat.group == "Wants":
        return "want"
    return None


def is_valid_key(key: str) -> bool:
    """Return True if key is in the canonical taxonomy."""
    return key in VALID_KEYS


def display_path(key: str) -> str:
    """Return a human-readable path like 'Expenses / Wants / Restaurants'."""
    cat = BY_KEY.get(key)
    if cat is None:
        return key  # custom user category: show raw
    if cat.top_type == cat.group:
        return f"{cat.top_type} / {cat.name}"
    return f"{cat.top_type} / {cat.group} / {cat.name}"

"""
classify_bucket — wrap tools/categorize.py with sector-hint override.

Priority:
  1. Sector column value (confidence 0.85) if non-empty and mappable.
  2. Deterministic rules from categorize_transaction() (confidence 0.9).
  3. LLM fallback placeholder (confidence 0.5) for truly unknown merchants.

Returns (bucket, confidence) where bucket ∈ {"need", "want", "savings"}.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import Transaction

# Sector → bucket mapping from bank category labels (e.g. Mastercard "Sector" column)
_SECTOR_MAP: dict[str, str] = {
    # needs
    "grocery stores": "need",
    "supermarkets": "need",
    "food & drug stores": "need",
    "pharmacies": "need",
    "health & beauty": "need",
    "medical services": "need",
    "insurance": "need",
    "utilities": "need",
    "telephone services": "need",
    "transportation": "need",
    "fuel dealers": "need",
    "postal services": "need",
    # wants
    "restaurants": "want",
    "fast food restaurants": "want",
    "eating places": "want",
    "bars & nightclubs": "want",
    "entertainment": "want",
    "digital": "want",
    "digital goods": "want",
    "clothing": "want",
    "clothing stores": "want",
    "sporting goods": "want",
    "electronics": "want",
    "computer equipment": "want",
    "travel": "want",
    "hotels": "want",
    "airlines": "want",
    "streaming": "want",
    # savings
    "investment": "savings",
    "brokerage": "savings",
    "financial services": "savings",
}


def classify_bucket(
    txn: Transaction,
    sector_hint: str | None = None,
) -> tuple[str, float]:
    """Return (bucket, confidence).

    sector_hint is the raw bank category label from the CSV (e.g. "Grocery stores").
    """
    # Sector override first
    if sector_hint:
        norm = sector_hint.strip().lower()
        if norm in _SECTOR_MAP:
            return _SECTOR_MAP[norm], 0.85

    # Deterministic rules
    from tools.categorize import categorize_transaction, _RULES  # noqa: F401

    try:
        bucket = categorize_transaction(txn)
        # If it hit a known rule the confidence is high; default "want" fallback is lower.
        key = txn.merchant.lower()
        hit_rule = any(pattern in key for pattern, _ in _RULES)
        confidence = 0.9 if hit_rule else 0.5
        return bucket, confidence
    except ValueError:
        # Income (positive amount) — should not reach here
        return "savings", 0.5

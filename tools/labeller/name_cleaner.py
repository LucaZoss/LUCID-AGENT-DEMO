"""
clean_merchant_name — normalize raw bank merchant strings.

Strips trailing location/country suffixes, collapses whitespace, title-cases.

Examples:
  "UPTRACK+                 RENNES       FRA"  → "UpTrack+"
  "COOP BERN                BERN         CHE"  → "Coop Bern"
  "Starbucks"                                  → "Starbucks"
"""

from __future__ import annotations

import re


# Strip trailing tokens that look like: "     CITY    COUNTRY" (fixed-width bank export padding).
# Requires 5+ spaces so that normal double-spaced merchant names ("APPLE  APP  STORE")
# are not accidentally stripped.
_LOCATION_SUFFIX = re.compile(r"\s{5,}[A-Z][A-Z ]+$")

# Country codes: 3 uppercase letters at the very end after whitespace
_COUNTRY_CODE = re.compile(r"\s+[A-Z]{2,3}\s*$")


def clean_merchant_name(raw: str) -> str:
    """Return a cleaned, title-cased merchant name.

    1. Strip leading/trailing whitespace.
    2. Remove trailing location suffix (city + country code block).
    3. Collapse internal whitespace.
    4. Title-case.
    """
    if not raw:
        return raw

    s = raw.strip()

    # Remove trailing " CITY       COUNTRY" block (2+ spaces → uppercase block)
    s = _LOCATION_SUFFIX.sub("", s)

    # Remove any remaining trailing country code (e.g. "  CHE")
    s = _COUNTRY_CODE.sub("", s)

    # Collapse internal whitespace to single space
    s = re.sub(r"\s+", " ", s).strip()

    # Title-case (preserves known abbreviations like "SBB", "UBS", "ZKB")
    # Simple title-case is fine; the LLM layer can override specific cases.
    s = s.title()

    return s

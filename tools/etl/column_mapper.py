"""
Heuristic column mapping for CSV files.

Wraps ingest/csv_detect.py logic and computes a stable header fingerprint
(sha256 of sorted normalized headers) for format-memory lookups.
"""

from __future__ import annotations

import hashlib


def header_fingerprint(headers: list[str]) -> str:
    """Stable sha256 of sorted, normalized headers — used for format memory."""
    normalized = sorted(h.strip().lower() for h in headers)
    raw = "|".join(normalized)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def heuristic_map(headers: list[str]) -> dict:
    """Return the best auto-detected mapping for *headers*.

    Returns a dict with keys:
      - column_map: {lucid_field: csv_column}
      - sign_rule: 'single_amount' | 'single_amount_flipped' | 'debit_credit' | ''
      - ambiguous: bool
      - message: str (human-readable result or error)
      - header_fingerprint: str
    """
    from ingest.csv_detect import MappingAmbiguity, ResolvedColumnMapping, detect_mapping

    fp = header_fingerprint(headers)

    if not headers:
        return {
            "column_map": {},
            "sign_rule": "",
            "ambiguous": True,
            "message": "No headers provided.",
            "header_fingerprint": fp,
        }

    result = detect_mapping(headers, encoding="utf-8", delimiter=",")

    if isinstance(result, MappingAmbiguity):
        return {
            "column_map": result.best_effort,
            "sign_rule": "",
            "ambiguous": True,
            "message": result.message,
            "header_fingerprint": fp,
        }

    return {
        "column_map": result.column_map,
        "sign_rule": result.sign_rule,
        "ambiguous": False,
        "message": "auto-detected",
        "header_fingerprint": fp,
    }

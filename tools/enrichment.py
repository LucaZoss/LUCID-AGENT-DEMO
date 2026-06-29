"""
Deterministic ETL enrichment passes — run after CSV import and labeling.

No LLM calls. All results are written back to the transactions table.
Call enrich_transactions() to run all passes in the correct order.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone


# ── Transfer detection ───────────────────────────────────────────────────────

_TRANSFER_PATTERNS: frozenset[str] = frozenset({
    "twint",
    "überweisung",
    "virement",
    "transfer",
    "gutschrift",
    "bonification",
    "sepa",
    "dauerauftrag",
    "standing order",
    "ordre permanent",
    "internal",
    "eigene konten",
    "own account",
    "compte propre",
})

# normalized_category values that always represent a transfer flow
_TRANSFER_CATEGORIES: frozenset[str] = frozenset({"twint_credit", "twint_debit"})


def detect_transfers(conn: sqlite3.Connection, user_id: str) -> int:
    """Mark is_transfer=1 for inter-account transfer rows. Returns count updated."""
    rows = conn.execute(
        "SELECT t.id, t.merchant, t.normalized_category "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=?",
        (user_id,),
    ).fetchall()

    updated = 0
    for txn_id, merchant, norm_cat in rows:
        merchant_lower = merchant.lower()
        is_transfer = (
            any(pat in merchant_lower for pat in _TRANSFER_PATTERNS)
            or norm_cat in _TRANSFER_CATEGORIES
        )
        if is_transfer:
            conn.execute(
                "UPDATE transactions SET is_transfer=1 WHERE id=?", (txn_id,)
            )
            updated += 1

    conn.commit()
    return updated


# ── Recurrence detection ─────────────────────────────────────────────────────

_CADENCE_RANGES: list[tuple[str, int, int]] = [
    ("annual",   350, 380),
    ("monthly",   25,  35),
    ("biweekly",  12,  16),
    ("weekly",     6,   8),
]


def detect_recurring(
    conn: sqlite3.Connection,
    user_id: str,
    min_occurrences: int = 2,
) -> int:
    """Mark is_recurring=1 + recurrence_cadence for repeating merchant payments.

    A merchant is recurring when ≥ min_occurrences transactions exist and their
    average inter-arrival gap falls within one of the recognised cadence windows.
    Transfers are excluded (already flagged by detect_transfers).
    Returns count of transaction rows updated.
    """
    rows = conn.execute(
        "SELECT t.id, t.merchant, t.ts "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.is_transfer=0 "
        "ORDER BY t.merchant, t.ts",
        (user_id,),
    ).fetchall()

    by_merchant: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    for txn_id, merchant, ts_raw in rows:
        try:
            dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue
        by_merchant[merchant.lower().strip()].append((txn_id, dt))

    updated = 0
    for _merchant, entries in by_merchant.items():
        if len(entries) < min_occurrences:
            continue

        entries.sort(key=lambda x: x[1])
        deltas = [
            (entries[i][1] - entries[i - 1][1]).days
            for i in range(1, len(entries))
        ]
        if not deltas:
            continue

        avg_delta = sum(deltas) / len(deltas)
        cadence = next(
            (name for name, lo, hi in _CADENCE_RANGES if lo <= avg_delta <= hi),
            None,
        )
        if cadence is None:
            continue

        for txn_id, _ in entries:
            conn.execute(
                "UPDATE transactions SET is_recurring=1, recurrence_cadence=? WHERE id=?",
                (cadence, txn_id),
            )
            updated += 1

    conn.commit()
    return updated


# ── Fixed vs variable classification ────────────────────────────────────────

# Committed costs whose amount doesn't change month-to-month.
_FIXED_CATEGORIES: frozenset[str] = frozenset({
    "rent",
    "health_insurance",
    "telecom",
})


def classify_fixed_variable(conn: sqlite3.Connection, user_id: str) -> int:
    """Set is_fixed=1 for committed-cost categories. Returns count of rows updated."""
    rows = conn.execute(
        "SELECT t.id, t.normalized_category "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.normalized_category IS NOT NULL",
        (user_id,),
    ).fetchall()

    updated = 0
    for txn_id, norm_cat in rows:
        if norm_cat in _FIXED_CATEGORIES:
            conn.execute("UPDATE transactions SET is_fixed=1 WHERE id=?", (txn_id,))
            updated += 1

    conn.commit()
    return updated


# ── Confidence scoring ───────────────────────────────────────────────────────

_SOURCE_CONFIDENCE: dict[str, float] = {
    "user_confirmed": 1.0,
    "sector_rule":    0.8,
    "llm_proposed":   0.6,
}
# Fallback when a category was assigned by the deterministic code-rule path
# (map_from_merchant_key / map_from_line_category) but no override row exists.
_CODE_RULE_CONFIDENCE: float = 0.75


def score_confidence(conn: sqlite3.Connection, user_id: str) -> int:
    """Write enrichment_confidence to every categorised transaction.

    Priority (highest wins):
      1. User-accepted proposal  → 1.0
      2. merchant_category_overrides.confidence (source-weighted)
      3. Deterministic code-rule fallback → 0.75

    Only rows that already have a normalized_category are scored.
    Returns count of rows updated.
    """
    overrides: dict[str, tuple[str, float]] = {
        row[0]: (row[1], float(row[2]))
        for row in conn.execute(
            "SELECT merchant_normalized, source, confidence "
            "FROM merchant_category_overrides WHERE user_id=?",
            (user_id,),
        ).fetchall()
    }

    accepted_txn_ids: set[str] = {
        row[0]
        for row in conn.execute(
            "SELECT txn_id FROM category_proposals "
            "WHERE user_id=? AND status='accepted'",
            (user_id,),
        ).fetchall()
    }

    rows = conn.execute(
        "SELECT t.id, t.merchant, t.normalized_category "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.normalized_category IS NOT NULL",
        (user_id,),
    ).fetchall()

    updated = 0
    for txn_id, merchant, _norm_cat in rows:
        if txn_id in accepted_txn_ids:
            confidence = 1.0
        else:
            merchant_key = merchant.lower().strip()
            if merchant_key in overrides:
                source, override_conf = overrides[merchant_key]
                confidence = override_conf if override_conf else _SOURCE_CONFIDENCE.get(source, 0.6)
            else:
                confidence = _CODE_RULE_CONFIDENCE

        conn.execute(
            "UPDATE transactions SET enrichment_confidence=? WHERE id=?",
            (round(confidence, 3), txn_id),
        )
        updated += 1

    conn.commit()
    return updated


# ── Deterministic category normalizer ───────────────────────────────────────
# Writes normalized_category directly from line_category + merchant rules,
# bypassing the HIL proposal queue for high-confidence deterministic matches.
# Unknown merchants are left NULL so the user can classify them via /cat-run.

def auto_normalize_categories(conn: sqlite3.Connection, user_id: str) -> int:
    """Write normalized_category for rows that can be determined without LLM.

    Called automatically at the start of enrich_transactions() so that
    classify_fixed_variable() and score_confidence() have data to work with
    even when the user hasn't yet run /cat-run in the REPL.

    Prioritises (in order):
      1. Existing normalized_category (already set — skipped)
      2. line_category → normalized key via categories_mapping
      3. Merchant substring patterns via categories_mapping
      4. Salary heuristic: positive amount + no other match → 'salary'

    Returns count of rows updated.
    """
    from categories_mapping import map_from_line_category, map_from_merchant_key

    rows = conn.execute(
        "SELECT t.id, t.merchant, t.line_category, t.amount "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.normalized_category IS NULL",
        (user_id,),
    ).fetchall()

    updated = 0
    for txn_id, merchant, line_cat, amount in rows:
        norm_key: str | None = None

        if line_cat:
            norm_key = map_from_line_category(line_cat)

        if not norm_key:
            merchant_lower = merchant.lower().strip()
            norm_key = map_from_merchant_key(merchant_lower)
            if norm_key == "twint_debit" and (amount or 0) > 0:
                norm_key = "twint_credit"

        if not norm_key and (amount or 0) > 0:
            norm_key = "salary"

        if norm_key:
            conn.execute(
                "UPDATE transactions SET normalized_category=? WHERE id=?",
                (norm_key, txn_id),
            )
            updated += 1

    conn.commit()
    return updated


# ── Master enrichment runner ─────────────────────────────────────────────────

def enrich_transactions(conn: sqlite3.Connection, user_id: str) -> dict[str, int]:
    """Run all enrichment passes in dependency order. Returns a summary dict.

    Pass order:
      0. auto_normalize  — fill normalized_category from line_category + patterns
      1. detect_transfers — must run before recurrence (transfers excluded)
      2. detect_recurring — per-merchant cadence analysis
      3. classify_fixed   — committed vs discretionary spend
      4. score_confidence — weight per merchant override source
    """
    normalized = auto_normalize_categories(conn, user_id)
    transfers = detect_transfers(conn, user_id)
    recurring = detect_recurring(conn, user_id)
    fixed = classify_fixed_variable(conn, user_id)
    scored = score_confidence(conn, user_id)
    return {
        "auto_normalized":     normalized,
        "transfers_flagged":   transfers,
        "recurring_detected":  recurring,
        "fixed_classified":    fixed,
        "confidence_scored":   scored,
    }

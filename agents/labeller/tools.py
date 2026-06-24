"""
Deterministic tool implementations for the Labeller Agent.

No LLM. The agent calls these via its tool-calling loop; conn/user_id are
injected by the dispatcher, not passed by the LLM.

Design contract:
  - The Labeller writes *line_category* (descriptive: "Grocery Stores",
    "Electronics Stores", …) and *clean_name* to transactions.
  - It does NOT write *category* (need/want/savings) — that is the budget
    agent's responsibility.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from categories import VALID_KEYS, is_valid_key
from tools.labeller.name_cleaner import clean_merchant_name

# Vocabulary for the /rules flow: the canonical normalized taxonomy keys.
RULE_LINE_CATEGORIES: frozenset[str] = VALID_KEYS

# Merchant-substring → normalized_category key (ordered, first match wins).
_MERCHANT_LINE_RULES: list[tuple[str, str]] = [
    # Groceries & supermarkets
    ("coop",           "groceries_food"),
    ("migros",         "groceries_food"),
    ("aldi",           "groceries_food"),
    ("lidl",           "groceries_food"),
    ("denner",         "groceries_food"),
    ("volg",           "groceries_food"),
    ("spar",           "groceries_food"),
    # Pharmacies & health
    ("apotheke",       "health_other"),
    ("pharmacy",       "health_other"),
    ("pharmacie",      "health_other"),
    ("medikament",     "health_other"),
    ("drogerien",      "health_other"),
    # Restaurants & food delivery (coffee shops included)
    ("starbucks",      "restaurants"),
    ("caffè nero",     "restaurants"),
    ("mcdonalds",      "restaurants"),
    ("mc donalds",     "restaurants"),
    ("burger king",    "restaurants"),
    ("kfc",            "restaurants"),
    ("subway",         "restaurants"),
    ("pizza",          "restaurants"),
    ("sushi",          "restaurants"),
    ("doordash",       "restaurants"),
    ("uber eats",      "restaurants"),
    ("just eat",       "restaurants"),
    ("smood",          "restaurants"),
    # Streaming, software & digital goods
    ("netflix",        "digital_goods"),
    ("spotify",        "digital_goods"),
    ("disney",         "digital_goods"),
    ("apple tv",       "digital_goods"),
    ("youtube",        "digital_goods"),
    ("amazon prime",   "digital_goods"),
    ("apple.com",      "digital_goods"),
    ("google play",    "digital_goods"),
    ("adobe",          "digital_goods"),
    ("microsoft",      "digital_goods"),
    ("github",         "digital_goods"),
    ("anthropic",      "digital_goods"),
    ("openai",         "digital_goods"),
    ("chatgpt",        "digital_goods"),
    # Electronics stores (also digital_goods)
    ("digitec",        "digital_goods"),
    ("galaxus",        "digital_goods"),
    ("mediamarkt",     "digital_goods"),
    # Online shopping
    ("amazon",         "wants_other"),
    # Clothing
    ("zalando",        "clothing"),
    ("zara",           "clothing"),
    ("h&m",            "clothing"),
    # Transport (public)
    ("sbb",            "transport"),
    ("bls",            "transport"),
    ("postauto",       "transport"),
    ("uber",           "transport"),
    ("lyft",           "transport"),
    ("taxis",          "transport"),
    ("taxi",           "transport"),
    # Banking fees
    ("zkb",            "extras_other"),
    ("annual fee",     "extras_other"),
    ("jahresgebühr",   "extras_other"),
    ("kontogebühr",    "extras_other"),
    # Car / fuel
    ("shell",          "car"),
    ("bp ",            "car"),
    ("esso",           "car"),
    ("agrola",         "car"),
    ("tamoil",         "car"),
    # Telecoms
    ("sunrise",        "telecom"),
    ("salt",           "telecom"),
    ("swisscom",       "telecom"),
    # Utilities / housing
    ("ewz",            "housing"),
    ("ckw",            "housing"),
    # Health insurance (Swiss Krankenkasse)
    ("swica",          "health_insurance"),
    ("helsana",        "health_insurance"),
    ("css versicherung","health_insurance"),
    ("assura",         "health_insurance"),
    ("concordia",      "health_insurance"),
    # Sports & fitness
    ("gym",            "sports"),
    ("fitnesspark",    "sports"),
    ("migros sport",   "sports"),
    # Travel & accommodation
    ("airbnb",         "travel_holidays"),
    ("booking.com",    "travel_holidays"),
    ("hotels.com",     "travel_holidays"),
    ("lufthansa",      "travel_holidays"),
    ("swiss air",      "travel_holidays"),
    ("easyjet",        "travel_holidays"),
    ("ryanair",        "travel_holidays"),
]


def fetch_unlabelled(
    conn: sqlite3.Connection,
    user_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Return outflow transactions that are missing a line_category."""
    rows = conn.execute(
        "SELECT t.id, t.merchant, t.amount, t.ts, t.line_category "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.amount < 0 AND t.line_category IS NULL "
        "ORDER BY t.ts DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    txns = [
        {
            "txn_id": r[0],
            "merchant": r[1],
            "amount": r[2],
            "ts": r[3],
            "sector_hint": r[4],
        }
        for r in rows
    ]
    return {"ok": True, "count": len(txns), "transactions": txns}


def lookup_merchant_memory(
    conn: sqlite3.Connection,
    user_id: str,
    merchant: str,
) -> dict[str, Any]:
    """Check merchant_category_overrides for a known line_category."""
    key = merchant.strip().lower()
    row = conn.execute(
        "SELECT canonical_name, bucket, line_category, source, confidence, "
        "override_count, normalized_category "
        "FROM merchant_category_overrides "
        "WHERE user_id=? AND merchant_normalized=?",
        (user_id, key),
    ).fetchone()
    if not row:
        return {"found": False, "merchant": merchant}
    return {
        "found": True,
        "merchant": merchant,
        "canonical_name": row[0],
        "bucket": row[1],
        "line_category": row[2],
        "source": row[3],
        "confidence": row[4],
        "override_count": row[5],
        "normalized_category": row[6],
        # Auto-apply when user explicitly confirmed AND we have a line_category
        "auto_apply": (
            row[3] == "user_confirmed"
            and row[2] is not None
            and (row[4] or 0.0) >= 1.0
        ),
    }


def propose_clean_name(merchant: str) -> dict[str, Any]:
    """Return the deterministic clean display name for a raw merchant string."""
    clean = clean_merchant_name(merchant)
    return {"merchant": merchant, "clean_name": clean}


def propose_line_category(
    merchant: str,
    sector_hint: str | None = None,
) -> dict[str, Any]:
    """Return a proposed descriptive line_category for a merchant.

    Priority:
    1. sector_hint (raw bank category from CSV) — use title-cased as-is.
    2. Merchant substring rules → descriptive label.
    3. Unknown → line_category=None so the agent uses its own judgment.
    """
    if sector_hint and sector_hint.strip():
        return {
            "merchant": merchant,
            "line_category": sector_hint.strip().title(),
            "confidence": 0.85,
            "source": "sector_hint",
        }

    key = merchant.strip().lower()
    for pattern, category in _MERCHANT_LINE_RULES:
        if pattern in key:
            return {
                "merchant": merchant,
                "line_category": category,
                "confidence": 0.9,
                "source": "rule",
            }

    return {
        "merchant": merchant,
        "line_category": None,
        "confidence": 0.0,
        "source": "unknown",
    }


def detect_merchant_patterns(
    transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Group transactions by normalized merchant prefix.

    Returns groups with 2+ occurrences — candidates for a saved rule.
    Singles are returned separately so the agent can still propose categories.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in transactions:
        raw = t.get("merchant", "")
        # Normalize: clean name → lowercase → strip trailing digits/IDs
        key = clean_merchant_name(raw).lower()
        key = re.sub(r"[\s\-_]+\d+\s*$", "", key).strip()
        groups[key].append(t)

    patterns = []
    singles = []
    for key, group in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(group) >= 2:
            patterns.append({
                "pattern": key,
                "count": len(group),
                "txn_ids": [t["txn_id"] for t in group],
                "example_merchant": group[0]["merchant"],
                "total_amount_chf": round(sum(t.get("amount", 0) for t in group), 2),
            })
        else:
            singles.extend(group)

    return {"ok": True, "patterns": patterns, "singles": singles}


def batch_confirm_with_user(
    transactions: list[dict[str, Any]],
    console,
) -> list[dict[str, Any]]:
    """Display tiered confirmation UI; return list of confirmed label dicts.

    Each transaction dict should have:
      txn_id, merchant, amount, clean_name, proposed_line_category,
      confidence, auto_apply (bool), sector_hint (optional),
      pattern_key (optional — present when part of a detected pattern),
      pattern_count (optional — how many rows share this pattern),
      is_pattern_lead (optional — True for only the first row in a pattern group).

    AUTO-APPLIED tier (auto_apply=True, confidence >= 1.0):
      → single bulk-accept prompt.

    PATTERN groups (pattern_key set, is_pattern_lead=True):
      → shown once per group: "N× Merchant → [category]  save as rule? [Y/n]"

    INDIVIDUAL review:
      → per-row: Enter=accept, e=edit category, s=skip
    """
    auto_applied: list[dict[str, Any]] = []
    needs_review: list[dict[str, Any]] = []

    for t in transactions:
        if t.get("auto_apply") and t.get("confidence", 0) >= 1.0:
            auto_applied.append(t)
        else:
            needs_review.append(t)

    confirmed: list[dict[str, Any]] = []

    # ── Auto-applied tier ──────────────────────────────────────────────────────
    if auto_applied:
        console.print(
            f"\n  [dim]{len(auto_applied)} transaction(s) auto-applied from merchant memory.[/dim]"
        )
        try:
            from rich.prompt import Confirm
            ok = Confirm.ask(
                f"  Accept all {len(auto_applied)} auto-applied label(s)?", default=True
            )
        except (EOFError, KeyboardInterrupt):
            ok = True
        if ok:
            for t in auto_applied:
                confirmed.append({
                    "txn_id": t["txn_id"],
                    "clean_name": t.get("clean_name") or t.get("merchant", ""),
                    "line_category": t.get("proposed_line_category") or t.get("line_category", ""),
                    "source": "user_confirmed",
                    "save_rule": False,
                })
        else:
            needs_review.extend(auto_applied)

    # ── Needs review tier ──────────────────────────────────────────────────────
    if needs_review:
        console.print(
            f"\n  [bold]{len(needs_review)} transaction(s) need review.[/bold]\n"
            "  [dim]Enter=accept · e=edit category · s=skip[/dim]\n"
        )

        # Separate pattern-lead rows from non-pattern rows
        seen_patterns: set[str] = set()
        pattern_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
        ordered: list[dict[str, Any]] = []

        for t in needs_review:
            pk = t.get("pattern_key")
            if pk:
                pattern_members[pk].append(t)
                if pk not in seen_patterns:
                    seen_patterns.add(pk)
                    ordered.append(t)  # lead row for this pattern
            else:
                ordered.append(t)

        for t in ordered:
            raw = t.get("merchant", "")
            clean = t.get("clean_name") or clean_merchant_name(raw)
            proposed = t.get("proposed_line_category") or ""
            amount = t.get("amount", 0.0)
            sector = t.get("sector_hint") or ""
            conf = t.get("confidence", 0.5)
            pk = t.get("pattern_key")

            if pk and pk in pattern_members:
                # Pattern group — show as a group
                group = pattern_members[pk]
                total = round(sum(g.get("amount", 0) for g in group), 2)
                console.print(
                    f"\n  [bold yellow]{len(group)}×[/bold yellow] [bold]{clean}[/bold] "
                    f"  [dim]total CHF {total:,.2f}[/dim]"
                )
                console.print(
                    f"    proposed category: [cyan]{proposed or '—'}[/cyan]  "
                    f"[dim](conf {conf:.0%})[/dim]"
                )
            else:
                console.print(
                    f"\n  [bold]{raw[:45]}[/bold]\n"
                    f"    clean: [cyan]{clean}[/cyan]  "
                    f"amount: [red]{amount:.2f}[/red] CHF  "
                    f"category: [bold]{proposed or '—'}[/bold]  "
                    f"[dim]{sector or ''}  (conf {conf:.0%})[/dim]"
                )

            try:
                raw_input = console.input(
                    "    [dim](Enter=accept, e=edit, s=skip)[/dim] › "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                raw_input = ""

            if raw_input == "s":
                # skip — do not label this transaction now
                continue

            if raw_input == "e":
                try:
                    new_cat = console.input(
                        f"    Category [{proposed or 'e.g. Electronics Stores'}]: "
                    ).strip()
                    proposed = new_cat or proposed
                except (EOFError, KeyboardInterrupt):
                    pass

            save_rule = False
            if pk and pk in pattern_members:
                # Offer to save as a rule for future transactions
                try:
                    from rich.prompt import Confirm
                    save_rule = Confirm.ask(
                        f"    Save rule: '{clean}' → '{proposed}' for future transactions?",
                        default=True,
                    )
                except (EOFError, KeyboardInterrupt):
                    save_rule = False

                # Apply to every member of the pattern group
                for member in pattern_members[pk]:
                    member_clean = member.get("clean_name") or clean_merchant_name(member.get("merchant", ""))
                    confirmed.append({
                        "txn_id": member["txn_id"],
                        "clean_name": member_clean,
                        "line_category": proposed,
                        "source": "user_confirmed",
                        "save_rule": save_rule,
                    })
            else:
                confirmed.append({
                    "txn_id": t["txn_id"],
                    "clean_name": clean,
                    "line_category": proposed,
                    "source": "user_confirmed",
                    "save_rule": False,
                })

    return confirmed


def apply_labels(
    conn: sqlite3.Connection,
    user_id: str,
    confirmed: list[dict[str, Any]],
    merchant_raw_map: dict[str, str],
) -> dict[str, Any]:
    """Write clean_name + line_category + normalized_category to transactions;
    upsert merchant_category_overrides.

    Intentionally does NOT write to the *category* (need/want/savings) column —
    that is the budget agent's responsibility.

    When save_rule=True the merchant override is stored so future imports of the
    same merchant are auto-labelled.
    """
    from categories_mapping import map_from_line_category

    now = datetime.now(timezone.utc).isoformat()
    applied = 0
    rules_saved = 0

    for item in confirmed:
        txn_id = item["txn_id"]
        clean_name = item["clean_name"]
        line_category = item.get("line_category") or ""
        save_rule = item.get("save_rule", False)
        # If the labeller already emits a normalized key, use it directly.
        if line_category and is_valid_key(line_category):
            norm_cat = line_category
        else:
            norm_cat = map_from_line_category(line_category) if line_category else None

        conn.execute(
            "UPDATE transactions SET clean_name=?, line_category=?, normalized_category=? WHERE id=?",
            (clean_name, line_category, norm_cat, txn_id),
        )
        applied += 1

        raw_merchant = merchant_raw_map.get(txn_id, "")
        if not raw_merchant:
            continue
        merchant_key = raw_merchant.strip().lower()

        existing = conn.execute(
            "SELECT id, override_count FROM merchant_category_overrides "
            "WHERE user_id=? AND merchant_normalized=?",
            (user_id, merchant_key),
        ).fetchone()

        if existing:
            new_count = (existing[1] or 0) + 1
            confidence = 1.0 if save_rule else 0.9
            source = "user_confirmed" if save_rule else "labeller_proposed"
            conn.execute(
                "UPDATE merchant_category_overrides "
                "SET canonical_name=?, line_category=?, normalized_category=?, source=?, "
                "confidence=?, override_count=?, updated_at=? "
                "WHERE id=?",
                (clean_name, line_category, norm_cat, source, confidence, new_count, now, existing[0]),
            )
            if save_rule:
                rules_saved += 1
        elif save_rule:
            conn.execute(
                "INSERT INTO merchant_category_overrides("
                "id, user_id, merchant_normalized, canonical_name, line_category, "
                "normalized_category, source, confidence, override_count, updated_at"
                ") VALUES (?,?,?,?,?,?,'user_confirmed',1.0,0,?)",
                (str(uuid.uuid4()), user_id, merchant_key, clean_name, line_category, norm_cat, now),
            )
            rules_saved += 1

    conn.commit()
    return {"ok": True, "applied": applied, "rules_saved": rules_saved}

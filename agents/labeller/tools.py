"""
Deterministic tool implementations for the Labeller Agent.

No LLM. The agent calls these via its tool-calling loop; conn/user_id are
injected by the dispatcher, not passed by the LLM.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from tools.labeller.name_cleaner import clean_merchant_name
from tools.labeller.bucket_classifier import classify_bucket


def fetch_unlabelled(
    conn: sqlite3.Connection,
    user_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Return outflow transactions without a clean_name or category."""
    rows = conn.execute(
        "SELECT t.id, t.merchant, t.amount, t.ts, t.line_category "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.amount < 0 "
        "  AND (t.clean_name IS NULL OR t.category IS NULL) "
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
    """Check merchant_category_overrides for a known clean-name / bucket."""
    key = merchant.strip().lower()
    row = conn.execute(
        "SELECT canonical_name, bucket, line_category, source, confidence, override_count "
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
        "auto_apply": row[3] == "user_confirmed" and (row[4] or 0.0) >= 1.0 and (row[5] or 0) < 3,
    }


def propose_clean_name(merchant: str) -> dict[str, Any]:
    """Return the deterministic clean name for a raw merchant string."""
    clean = clean_merchant_name(merchant)
    return {"merchant": merchant, "clean_name": clean}


def propose_bucket(
    merchant: str,
    amount: float,
    sector_hint: str | None = None,
) -> dict[str, Any]:
    """Return the proposed bucket and confidence for a transaction."""
    from contracts import Transaction
    txn = Transaction(
        id="tmp",
        account_id="tmp",
        amount=amount,
        currency="CHF",
        merchant=merchant,
        category=None,
        ts="2026-01-01T00:00:00+00:00",
    )
    bucket, confidence = classify_bucket(txn, sector_hint=sector_hint)
    return {
        "merchant": merchant,
        "proposed_bucket": bucket,
        "confidence": confidence,
    }


def batch_confirm_with_user(
    txns: list[dict[str, Any]],
    console,
) -> list[dict[str, Any]]:
    """Display tiered confirmation UI; return list of confirmed label dicts.

    AUTO-APPLIED tier (confidence >= 1.0 AND source = user_confirmed AND use_count >= 2):
      → accepted with a single keypress, no per-row display.

    NEEDS REVIEW tier (new or confidence < 1.0):
      → table: raw name | clean name | CHF | proposed bucket | sector hint
      → per-row: Enter=accept, n=need, w=want, s=savings, e=edit name
    """
    auto_applied: list[dict[str, Any]] = []
    needs_review: list[dict[str, Any]] = []

    for t in txns:
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
                    "bucket": t.get("proposed_bucket") or t.get("bucket", "want"),
                    "source": "user_confirmed",
                })
        else:
            needs_review.extend(auto_applied)

    # ── Needs review tier ──────────────────────────────────────────────────────
    if needs_review:
        from rich.table import Table

        console.print(
            f"\n  [bold]{len(needs_review)} transaction(s) need review.[/bold]\n"
            "  [dim]Enter=accept, n=need, w=want, s=savings, e=edit name[/dim]\n"
        )
        for t in needs_review:
            raw = t.get("merchant", "")
            clean = t.get("clean_name") or clean_merchant_name(raw)
            bucket = t.get("proposed_bucket") or "want"
            amount = t.get("amount", 0.0)
            sector = t.get("sector_hint") or ""
            conf = t.get("confidence", 0.5)

            console.print(
                f"  [bold]{raw[:40]}[/bold]\n"
                f"    clean: [cyan]{clean}[/cyan]  "
                f"amount: [red]{amount:.2f}[/red] CHF  "
                f"proposed: [bold]{bucket}[/bold]  "
                f"sector: [dim]{sector or '—'}[/dim]  "
                f"[dim](conf {conf:.0%})[/dim]"
            )
            try:
                raw_input = console.input(
                    "    [dim](Enter=accept, n/w/s=override, e=edit name)[/dim] › "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                raw_input = ""

            if raw_input == "e":
                try:
                    new_name = console.input(f"    New name [{clean}]: ").strip()
                    clean = new_name or clean
                except (EOFError, KeyboardInterrupt):
                    pass
                try:
                    raw_input = console.input(
                        "    [dim](Enter=accept, n/w/s=override)[/dim] › "
                    ).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    raw_input = ""

            bucket_map = {"n": "need", "w": "want", "s": "savings"}
            final_bucket = bucket_map.get(raw_input, bucket)

            confirmed.append({
                "txn_id": t["txn_id"],
                "clean_name": clean,
                "bucket": final_bucket,
                "source": "user_confirmed",
            })

    return confirmed


def apply_labels(
    conn: sqlite3.Connection,
    user_id: str,
    confirmed: list[dict[str, Any]],
    merchant_raw_map: dict[str, str],
) -> dict[str, Any]:
    """Write clean_name + category to transactions; upsert merchant_category_overrides.

    merchant_raw_map: {txn_id -> raw merchant string} (needed for the merchant key).
    """
    now = datetime.now(timezone.utc).isoformat()
    applied = 0

    for item in confirmed:
        txn_id = item["txn_id"]
        clean_name = item["clean_name"]
        bucket = item["bucket"]

        conn.execute(
            "UPDATE transactions SET clean_name=?, category=? WHERE id=?",
            (clean_name, bucket, txn_id),
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
            conn.execute(
                "UPDATE merchant_category_overrides "
                "SET canonical_name=?, bucket=?, source='user_confirmed', "
                "confidence=1.0, override_count=?, updated_at=? "
                "WHERE id=?",
                (clean_name, bucket, new_count, now, existing[0]),
            )
        else:
            conn.execute(
                "INSERT INTO merchant_category_overrides("
                "id, user_id, merchant_normalized, canonical_name, bucket, "
                "source, confidence, override_count, updated_at"
                ") VALUES (?,?,?,?,?,'user_confirmed',1.0,0,?)",
                (str(uuid.uuid4()), user_id, merchant_key, clean_name, bucket, now),
            )

    conn.commit()
    return {"ok": True, "applied": applied}

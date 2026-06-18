"""
Tool handlers for the ledger categorization agent — proposals only (HIL commit elsewhere).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

# Closed vocabulary aligned with SimulatedBank / budget line items (plan).
LINE_CATEGORY_VOCABULARY: frozenset[str] = frozenset({
    "rent",
    "health_insurance",
    "groceries",
    "transport",
    "telecom",
    "utilities",
    "dining",
    "coffee",
    "entertainment",
    "clothing",
    "electronics",
    "pharmacy",
    "bars",
    "streaming",
    "savings_transfer",
    "other",
})

NWS_BUCKETS: frozenset[str] = frozenset({"need", "want", "savings"})


def _txn_exists_for_user(
    conn: sqlite3.Connection, user_id: str, txn_id: str
) -> tuple[bool, float, str]:
    row = conn.execute(
        "SELECT t.amount, t.merchant FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id "
        "WHERE t.id=? AND a.user_id=?",
        (txn_id, user_id),
    ).fetchone()
    if not row:
        return False, 0.0, ""
    return True, row[0], row[1]


def _get_or_create_pending_id(
    conn: sqlite3.Connection, user_id: str, txn_id: str
) -> str:
    """Return proposal row id for the single pending row per txn (merge updates)."""
    row = conn.execute(
        "SELECT id FROM category_proposals WHERE txn_id=? AND user_id=? "
        "AND status='pending' ORDER BY created_at DESC LIMIT 1",
        (txn_id, user_id),
    ).fetchone()
    if row:
        return str(row[0])
    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO category_proposals("
        "id, user_id, txn_id, proposed_bucket, proposed_line, rationale, status, created_at"
        ") VALUES (?,?,?,?,?,?, 'pending', ?)",
        (pid, user_id, txn_id, None, None, None, now),
    )
    return pid


def propose_spending_bucket(
    conn: sqlite3.Connection,
    user_id: str,
    txn_id: str,
    merchant: str,
    proposed_bucket: str,
    *,
    rationale: str = "",
) -> dict[str, Any]:
    """Validate NWS bucket and upsert pending proposal."""
    ok, amount, db_merchant = _txn_exists_for_user(conn, user_id, txn_id)
    if not ok:
        return {"ok": False, "error": "transaction not found"}
    if amount >= 0:
        return {"ok": False, "error": "income rows are not bucketed here"}
    b = proposed_bucket.strip().lower()
    if b not in NWS_BUCKETS:
        return {"ok": False, "error": f"invalid bucket (need|want|savings): {proposed_bucket!r}"}
    pid = _get_or_create_pending_id(conn, user_id, txn_id)
    conn.execute(
        "UPDATE category_proposals SET proposed_bucket=?, "
        "rationale=COALESCE(?, rationale) WHERE id=?",
        (b, rationale or None, pid),
    )
    conn.commit()
    return {
        "ok": True,
        "proposal_id": pid,
        "txn_id": txn_id,
        "merchant": merchant or db_merchant,
        "proposed_bucket": b,
    }


def propose_line_category(
    conn: sqlite3.Connection,
    user_id: str,
    txn_id: str,
    merchant: str,
    proposed_line: str,
    *,
    rationale: str = "",
) -> dict[str, Any]:
    """Validate fine line label and merge into the pending proposal row."""
    ok, amount, db_merchant = _txn_exists_for_user(conn, user_id, txn_id)
    if not ok:
        return {"ok": False, "error": "transaction not found"}
    if amount >= 0:
        return {"ok": False, "error": "income rows are not line-tagged here"}
    line = proposed_line.strip().lower().replace(" ", "_")
    if line not in LINE_CATEGORY_VOCABULARY:
        return {
            "ok": False,
            "error": f"invalid line_category; allowed: {sorted(LINE_CATEGORY_VOCABULARY)}",
        }
    pid = _get_or_create_pending_id(conn, user_id, txn_id)
    conn.execute(
        "UPDATE category_proposals SET proposed_line=?, "
        "rationale=COALESCE(?, rationale) WHERE id=?",
        (line, rationale or None, pid),
    )
    conn.commit()
    row = conn.execute(
        "SELECT proposed_bucket FROM category_proposals WHERE id=?",
        (pid,),
    ).fetchone()
    return {
        "ok": True,
        "proposal_id": pid,
        "txn_id": txn_id,
        "merchant": merchant or db_merchant,
        "proposed_line": line,
        "proposed_bucket": row[0] if row else None,
    }


def list_pending_proposals(
    conn: sqlite3.Connection, user_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT p.id, p.txn_id, p.proposed_bucket, p.proposed_line, p.rationale, "
        "p.created_at, t.merchant, t.amount "
        "FROM category_proposals p "
        "JOIN transactions t ON p.txn_id=t.id "
        "JOIN accounts a ON t.account_id=a.id "
        "WHERE p.user_id=? AND p.status='pending' AND a.user_id=? "
        "ORDER BY p.created_at DESC LIMIT ?",
        (user_id, user_id, limit),
    ).fetchall()
    return [
        {
            "proposal_id": r[0],
            "txn_id": r[1],
            "proposed_bucket": r[2],
            "proposed_line": r[3],
            "rationale": r[4],
            "created_at": r[5],
            "merchant": r[6],
            "amount": r[7],
        }
        for r in rows
    ]


def apply_proposal(
    conn: sqlite3.Connection,
    user_id: str,
    proposal_id: str,
    *,
    bucket_override: str | None = None,
    line_override: str | None = None,
) -> dict[str, Any]:
    """Accept proposal (with optional edits) and UPDATE transactions."""
    row = conn.execute(
        "SELECT p.txn_id, p.proposed_bucket, p.proposed_line FROM category_proposals p "
        "WHERE p.id=? AND p.user_id=? AND p.status='pending'",
        (proposal_id, user_id),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "proposal not found or not pending"}
    txn_id, pb, pl = row
    bucket = (bucket_override or pb or "").strip().lower()
    line = (line_override or pl or "").strip().lower().replace(" ", "_") or None
    if bucket and bucket not in NWS_BUCKETS:
        return {"ok": False, "error": f"invalid bucket: {bucket!r}"}
    if line and line not in LINE_CATEGORY_VOCABULARY:
        return {"ok": False, "error": f"invalid line: {line!r}"}
    if not bucket and not line:
        return {"ok": False, "error": "nothing to apply"}
    if bucket:
        conn.execute(
            "UPDATE transactions SET category=? WHERE id=?",
            (bucket, txn_id),
        )
    if line:
        conn.execute(
            "UPDATE transactions SET line_category=? WHERE id=?",
            (line, txn_id),
        )
    conn.execute(
        "UPDATE category_proposals SET status='accepted' WHERE id=?",
        (proposal_id,),
    )
    conn.execute(
        "UPDATE category_proposals SET status='rejected' WHERE txn_id=? AND id<>? "
        "AND status='pending'",
        (txn_id, proposal_id),
    )
    conn.commit()
    return {"ok": True, "txn_id": txn_id, "category": bucket or None, "line_category": line}


def reject_proposal(conn: sqlite3.Connection, user_id: str, proposal_id: str) -> bool:
    cur = conn.execute(
        "UPDATE category_proposals SET status='rejected' "
        "WHERE id=? AND user_id=? AND status='pending'",
        (proposal_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0

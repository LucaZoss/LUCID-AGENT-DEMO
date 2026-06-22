"""
Pure-Python tool implementations for the Database Manager Agent.

All functions are deterministic (no LLM). The agent calls them via
its tool-calling loop; conn/user_id/account_id are injected by the
dispatcher in db_manager.py, not passed by the LLM.
"""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Any

from ingest.csv_detect import MappingAmbiguity, ResolvedColumnMapping
from ingest.importer import import_csv_files, preview_csv_file


# ── 1. scan_csv_folder ────────────────────────────────────────────────────────

def scan_csv_folder(folder_path: str) -> dict[str, Any]:
    """List .csv files found in folder_path."""
    p = Path(folder_path).expanduser().resolve()
    if not p.is_dir():
        return {"ok": False, "error": f"Not a directory: {folder_path}"}
    files = sorted(str(f) for f in p.glob("*.csv"))
    return {"ok": True, "folder": str(p), "files": files, "count": len(files)}


# ── 2. analyze_csv_file ───────────────────────────────────────────────────────

def analyze_csv_file(file_path: str) -> dict[str, Any]:
    """Preview one CSV file: returns headers, samples, and auto-detected mapping."""
    p = Path(file_path).expanduser().resolve()
    if not p.is_file():
        return {"ok": False, "error": f"File not found: {file_path}"}

    preview = preview_csv_file(p)
    detected = preview["detection"]

    result: dict[str, Any] = {
        "ok": True,
        "file": p.name,
        "headers": preview["headers"],
        "encoding": preview["encoding"],
        "delimiter": preview["delimiter"],
        "sample_rows": [
            {k: str(v)[:60] for k, v in row.items()}
            for row in preview["sample_rows"][:3]
        ],
    }

    if isinstance(detected, ResolvedColumnMapping):
        result["detection"] = {
            "status": "ok",
            "column_map": detected.column_map,
            "sign_rule": detected.sign_rule,
            "category_col": detected.category_col,
        }
    else:
        # MappingAmbiguity — include partial guess so the LLM can ask the user to fill gaps
        result["detection"] = {
            "status": "ambiguous",
            "message": detected.message,
            "best_effort": detected.best_effort or {},
        }

    return result


# ── 3. import_file ────────────────────────────────────────────────────────────

def import_file(
    file_path: str,
    column_map: dict[str, str],
    sign_rule: str,
    account_id: str,
    user_id: str,
    conn: sqlite3.Connection,
    *,
    category_col: str | None = None,
    encoding: str = "utf-8",
    delimiter: str = ",",
) -> dict[str, Any]:
    """Import a CSV file using the confirmed column mapping."""
    p = Path(file_path).expanduser().resolve()
    if not p.is_file():
        return {"ok": False, "error": f"File not found: {file_path}"}

    mapping = ResolvedColumnMapping(
        column_map=column_map,
        sign_rule=sign_rule,
        encoding=encoding,
        delimiter=delimiter,
        category_col=category_col or None,
    )

    results = import_csv_files(conn, user_id, account_id, [p], mapping=mapping)
    if not results:
        return {"ok": False, "error": "No results returned from importer"}

    r = results[0]
    return {
        "ok": not r.skipped,
        "message": r.message,
        "batch_id": r.batch_id,
        "rows_inserted": r.rows_inserted,
        "rows_skipped_duplicate": r.rows_skipped_duplicate,
        "rows_skipped_invalid": r.rows_skipped_invalid,
        "warnings": r.warnings,
    }


# ── Deterministic line-category hints ─────────────────────────────────────────

_LINE_HINTS: dict[str, dict[str, str]] = {
    "need": {
        "coop": "groceries", "migros": "groceries", "aldi": "groceries",
        "lidl": "groceries", "denner": "groceries", "volg": "groceries",
        "helsana": "health_insurance", "swica": "health_insurance",
        "css": "health_insurance", "concordia": "health_insurance",
        "sbb": "transport", "postbus": "transport", "zvv": "transport",
        "swisscom": "telecom", "salt": "telecom", "sunrise": "telecom",
        "apotheke": "pharmacy", "pharmacie": "pharmacy",
        "miete": "rent", "loyer": "rent",
        "ewz": "utilities", "energie": "utilities",
    },
    "want": {
        "starbucks": "coffee", "coffee fellows": "coffee",
        "restaurant": "dining", "tibits": "dining", "mcdonald": "dining",
        "burger king": "dining", "subway": "dining",
        "netflix": "streaming", "spotify": "streaming",
        "zara": "clothing", "h&m": "clothing", "uniqlo": "clothing",
        "digitec": "electronics", "galaxus": "electronics",
        "kino": "entertainment", "theater": "entertainment", "cinema": "entertainment",
        "bar": "bars",
    },
    "savings": {
        "viac": "savings_transfer", "swissquote": "savings_transfer",
        "frankly": "savings_transfer", "neon invest": "savings_transfer",
    },
}


def _infer_line(merchant: str, bucket: str) -> str | None:
    hint_map = _LINE_HINTS.get(bucket, {})
    merchant_lower = merchant.lower()
    for keyword, line in hint_map.items():
        if keyword in merchant_lower:
            return line
    return None


# ── 4. propose_categories_for_batch ──────────────────────────────────────────

def propose_categories_for_batch(
    conn: sqlite3.Connection,
    user_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Classify uncategorized outflows deterministically and persist proposals.

    Returns a summary grouped by (bucket, line) so the LLM can present it
    clearly to the user for confirmation.
    """
    from tools.categorize import categorize_transaction
    from contracts import Transaction
    from agents.ledger_tools import propose_spending_bucket, propose_line_category

    rows = conn.execute(
        "SELECT t.id, t.merchant, t.amount, t.ts FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.amount < 0 AND t.category IS NULL "
        "ORDER BY t.ts DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()

    if not rows:
        return {"ok": True, "total": 0, "groups": [], "proposal_ids": []}

    groups: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    all_proposal_ids: list[str] = []

    for txn_id, merchant, amount, ts in rows:
        if isinstance(ts, str):
            try:
                ts_dt = datetime.datetime.fromisoformat(ts)
            except ValueError:
                ts_dt = datetime.datetime.now(datetime.timezone.utc)
        else:
            ts_dt = ts or datetime.datetime.now(datetime.timezone.utc)

        dummy = Transaction(
            id=txn_id,
            account_id="x",
            amount=float(amount),
            currency="CHF",
            merchant=merchant or "",
            category=None,
            ts=ts_dt,
        )
        bucket = categorize_transaction(dummy)
        line = _infer_line(merchant or "", bucket)

        r_bucket = propose_spending_bucket(
            conn, user_id, txn_id, merchant or "", bucket, rationale="deterministic"
        )
        if r_bucket.get("ok"):
            pid = r_bucket["proposal_id"]
            if line:
                propose_line_category(
                    conn, user_id, txn_id, merchant or "", line, rationale="deterministic"
                )
            all_proposal_ids.append(pid)

        key = (bucket, line)
        if key not in groups:
            groups[key] = []
        groups[key].append({"txn_id": txn_id, "merchant": merchant, "amount": float(amount)})

    groups_out = [
        {
            "bucket": k[0],
            "line": k[1] or "other",
            "count": len(v),
            "merchants": sorted({item["merchant"] for item in v if item["merchant"]}),
            "total_chf": round(sum(abs(item["amount"]) for item in v), 2),
        }
        for k, v in groups.items()
    ]

    return {
        "ok": True,
        "total": len(rows),
        "groups": groups_out,
        "proposal_ids": all_proposal_ids,
    }


# ── 5. accept_category_proposals ─────────────────────────────────────────────

def accept_category_proposals(
    conn: sqlite3.Connection,
    user_id: str,
    proposal_ids: list[str],
) -> dict[str, Any]:
    """Accept a list of pending category proposals, writing to transactions."""
    from agents.ledger_tools import apply_proposal

    accepted = 0
    errors: list[dict[str, str]] = []
    for pid in proposal_ids:
        result = apply_proposal(conn, user_id, pid)
        if result.get("ok"):
            accepted += 1
        else:
            errors.append({"proposal_id": pid, "error": result.get("error", "unknown")})

    return {"ok": True, "accepted": accepted, "total": len(proposal_ids), "errors": errors}


# ── 6. generate_import_summary ────────────────────────────────────────────────

def generate_import_summary(
    conn: sqlite3.Connection,
    user_id: str,
) -> dict[str, Any]:
    """Return aggregate import stats for the final summary display."""
    total_count = conn.execute(
        "SELECT COUNT(*) FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id WHERE a.user_id=?",
        (user_id,),
    ).fetchone()[0]

    date_range = conn.execute(
        "SELECT MIN(t.ts), MAX(t.ts) FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id WHERE a.user_id=?",
        (user_id,),
    ).fetchone()

    category_counts = conn.execute(
        "SELECT COALESCE(t.category, 'uncategorized'), COUNT(*) "
        "FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.amount < 0 "
        "GROUP BY t.category ORDER BY COUNT(*) DESC",
        (user_id,),
    ).fetchall()

    uncategorized = conn.execute(
        "SELECT COUNT(*) FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.amount < 0 AND t.category IS NULL",
        (user_id,),
    ).fetchone()[0]

    return {
        "ok": True,
        "total_transactions": total_count,
        "date_from": date_range[0],
        "date_to": date_range[1],
        "uncategorized_outflows": uncategorized,
        "category_breakdown": [
            {"category": row[0], "count": row[1]}
            for row in category_counts
        ],
    }

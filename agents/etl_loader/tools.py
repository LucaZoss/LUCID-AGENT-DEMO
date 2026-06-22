"""
Deterministic tool implementations for the ETL Loader Agent.

All functions are pure Python — no LLM. The agent calls them via its
tool-calling loop; conn/user_id/account_id are injected by the dispatcher,
not passed by the LLM.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingest.csv_detect import MappingAmbiguity, ResolvedColumnMapping, header_row_hash
from ingest.importer import import_csv_files, preview_csv_file
from tools.etl.column_mapper import header_fingerprint, heuristic_map
from tools.etl.complexity_analyzer import analyze_complexity


def scan_folder(folder_path: str) -> dict[str, Any]:
    """List .csv files found in folder_path."""
    p = Path(folder_path).expanduser().resolve()
    if not p.is_dir():
        return {"ok": False, "error": f"Not a directory: {folder_path}"}
    files = sorted(str(f) for f in p.glob("*.csv"))
    return {"ok": True, "folder": str(p), "files": files, "count": len(files)}


def check_complexity(file_path: str) -> dict[str, Any]:
    """Return ComplexityResult stats for a file."""
    result = analyze_complexity(file_path)
    return {
        "ok": True,
        "is_complex": result.is_complex,
        "strategy": result.strategy,
        "stats": result.stats,
    }


def lookup_format_profile(
    conn: sqlite3.Connection,
    user_id: str,
    file_path: str,
) -> dict[str, Any]:
    """Look up a confirmed format profile by file header fingerprint.

    Returns the profile if found and confirmed with use_count >= 2,
    plus the fingerprint computed from the file headers.
    """
    p = Path(file_path).expanduser().resolve()
    if not p.is_file():
        return {"ok": False, "found": False, "error": f"File not found: {file_path}"}

    try:
        preview = preview_csv_file(p)
    except Exception as exc:
        return {"ok": False, "found": False, "error": str(exc)}

    headers = preview.get("headers", [])
    fp = header_fingerprint(headers)
    hh = header_row_hash(headers, preview.get("delimiter", ","))

    row = conn.execute(
        "SELECT id, display_name, column_map, sign_rule, encoding, delimiter, "
        "confirmed, use_count, source_label, category_col "
        "FROM csv_mapping_profiles "
        "WHERE user_id=? AND header_hash=? "
        "ORDER BY use_count DESC, updated_at DESC LIMIT 1",
        (user_id, hh),
    ).fetchone()

    if not row:
        return {
            "ok": True,
            "found": False,
            "header_fingerprint": fp,
            "headers": headers,
            "preview": {
                "encoding": preview.get("encoding"),
                "delimiter": preview.get("delimiter"),
                "sample_rows": preview.get("sample_rows", [])[:3],
                "detection": _detection_to_dict(preview.get("detection")),
            },
        }

    return {
        "ok": True,
        "found": True,
        "profile_id": row[0],
        "display_name": row[1],
        "column_map": json.loads(row[2]),
        "sign_rule": row[3],
        "encoding": row[4],
        "delimiter": row[5],
        "confirmed": bool(row[6]),
        "use_count": row[7],
        "source_label": row[8],
        "category_col": row[9],
        "header_fingerprint": fp,
        "auto_apply": bool(row[6]) and (row[7] or 0) >= 2,
    }


def show_columns_ask_user(
    file_path: str,
    console,
    llm,
    conn: sqlite3.Connection | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Display columns and samples; collect mapping via HITL dialog.

    Delegates to the existing _show_columns_and_get_mapping() in startup.py
    so there is only one HITL dialog implementation.
    Returns dict with column_map, sign_rule, encoding, delimiter.
    """
    from orchestrator.startup import _show_columns_and_get_mapping
    from ingest.importer import preview_csv_file
    from ingest.csv_detect import MappingAmbiguity, ResolvedColumnMapping

    p = Path(file_path).expanduser().resolve()
    if not p.is_file():
        return {"ok": False, "error": f"File not found: {file_path}"}

    preview = preview_csv_file(p)
    mapping = _show_columns_and_get_mapping(
        console, llm, p, preview, conn=conn, user_id=user_id
    )
    if mapping is None:
        return {"ok": False, "skipped": True}

    return {
        "ok": True,
        "skipped": False,
        "column_map": mapping.column_map,
        "sign_rule": mapping.sign_rule,
        "encoding": mapping.encoding,
        "delimiter": mapping.delimiter,
        "category_col": mapping.category_col,
    }


def import_file(
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
    file_path: str,
    column_map: dict[str, str],
    sign_rule: str,
    encoding: str = "utf-8",
    delimiter: str = ",",
    category_col: str | None = None,
) -> dict[str, Any]:
    """Import a CSV using the provided mapping; return ImportResult stats."""
    from ingest.csv_detect import ResolvedColumnMapping

    p = Path(file_path).expanduser().resolve()
    mapping = ResolvedColumnMapping(
        column_map=column_map,
        sign_rule=sign_rule,
        encoding=encoding,
        delimiter=delimiter,
        category_col=category_col,
    )
    results = import_csv_files(conn, user_id, account_id, [p], mapping=mapping)
    if not results:
        return {"ok": False, "error": "No results returned from import_csv_files"}
    r = results[0]
    return {
        "ok": not r.skipped,
        "skipped": r.skipped,
        "message": r.message,
        "batch_id": r.batch_id,
        "rows_inserted": r.rows_inserted,
        "rows_skipped_duplicate": r.rows_skipped_duplicate,
        "rows_skipped_invalid": r.rows_skipped_invalid,
        "warnings": r.warnings,
    }


def save_format_profile(
    conn: sqlite3.Connection,
    user_id: str,
    file_path: str,
    column_map: dict[str, str],
    sign_rule: str,
    encoding: str = "utf-8",
    delimiter: str = ",",
    source_label: str | None = None,
    category_col: str | None = None,
) -> dict[str, Any]:
    """Persist a confirmed format profile; increment use_count if header already known."""
    from ingest.importer import preview_csv_file

    p = Path(file_path).expanduser().resolve()
    headers: list[str] = []
    if p.is_file():
        try:
            preview = preview_csv_file(p)
            headers = preview.get("headers", [])
            delimiter = preview.get("delimiter", delimiter)
            encoding = preview.get("encoding", encoding)
        except Exception:
            pass

    hh = header_row_hash(headers, delimiter) if headers else ""
    now = datetime.now(timezone.utc).isoformat()

    # Check if a profile for this header hash already exists
    existing = conn.execute(
        "SELECT id, use_count FROM csv_mapping_profiles "
        "WHERE user_id=? AND header_hash=? LIMIT 1",
        (user_id, hh),
    ).fetchone()

    if existing:
        pid = existing[0]
        new_count = (existing[1] or 0) + 1
        conn.execute(
            "UPDATE csv_mapping_profiles SET column_map=?, sign_rule=?, "
            "encoding=?, delimiter=?, confirmed=1, use_count=?, source_label=?, "
            "category_col=?, updated_at=? WHERE id=?",
            (
                json.dumps(column_map),
                sign_rule,
                encoding,
                delimiter,
                new_count,
                source_label,
                category_col,
                now,
                pid,
            ),
        )
    else:
        pid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO csv_mapping_profiles("
            "id, user_id, display_name, column_map, sign_rule, encoding, delimiter, "
            "header_hash, is_default, confirmed, use_count, source_label, "
            "category_col, created_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,0,1,1,?,?,?,?)",
            (
                pid,
                user_id,
                source_label or "imported format",
                json.dumps(column_map),
                sign_rule,
                encoding,
                delimiter,
                hh,
                source_label,
                category_col,
                now,
                now,
            ),
        )

    conn.commit()
    return {"ok": True, "profile_id": pid}


# ── helpers ────────────────────────────────────────────────────────────────────

def _detection_to_dict(detected: Any) -> dict:
    if detected is None:
        return {}
    if isinstance(detected, MappingAmbiguity):
        return {
            "ambiguous": True,
            "message": detected.message,
            "best_effort": detected.best_effort,
        }
    if isinstance(detected, ResolvedColumnMapping):
        return {
            "ambiguous": False,
            "column_map": detected.column_map,
            "sign_rule": detected.sign_rule,
        }
    return {}

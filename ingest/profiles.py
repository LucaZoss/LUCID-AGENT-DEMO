"""
CRUD for ``csv_mapping_profiles`` — persisted column layouts per user.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from ingest.csv_detect import header_row_hash


def list_profiles(conn: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    """Return all mapping profiles for the user."""
    rows = conn.execute(
        "SELECT id, display_name, column_map, sign_rule, encoding, delimiter, "
        "header_hash, is_default, created_at, updated_at "
        "FROM csv_mapping_profiles WHERE user_id=? ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": r[0],
            "display_name": r[1],
            "column_map": json.loads(r[2]),
            "sign_rule": r[3],
            "encoding": r[4],
            "delimiter": r[5],
            "header_hash": r[6],
            "is_default": bool(r[7]),
            "created_at": r[8],
            "updated_at": r[9],
        })
    return out


def get_profile(conn: sqlite3.Connection, profile_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, user_id, display_name, column_map, sign_rule, encoding, "
        "delimiter, header_hash, is_default FROM csv_mapping_profiles WHERE id=?",
        (profile_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "display_name": row[2],
        "column_map": json.loads(row[3]),
        "sign_rule": row[4],
        "encoding": row[5],
        "delimiter": row[6],
        "header_hash": row[7],
        "is_default": bool(row[8]),
    }


def find_profile_by_header_hash(
    conn: sqlite3.Connection, user_id: str, header_hash: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, user_id, display_name, column_map, sign_rule, encoding, "
        "delimiter, header_hash, is_default FROM csv_mapping_profiles "
        "WHERE user_id=? AND header_hash=? ORDER BY updated_at DESC LIMIT 1",
        (user_id, header_hash),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "display_name": row[2],
        "column_map": json.loads(row[3]),
        "sign_rule": row[4],
        "encoding": row[5],
        "delimiter": row[6],
        "header_hash": row[7],
        "is_default": bool(row[8]),
    }


def save_profile(
    conn: sqlite3.Connection,
    user_id: str,
    display_name: str,
    column_map: dict[str, str],
    *,
    sign_rule: str | None,
    encoding: str,
    delimiter: str,
    headers: list[str],
) -> str:
    """Insert a new profile; returns profile id."""
    now = datetime.now(timezone.utc).isoformat()
    pid = str(uuid.uuid4())
    hhash = header_row_hash(headers, delimiter)
    conn.execute(
        "INSERT INTO csv_mapping_profiles("
        "id, user_id, display_name, column_map, sign_rule, encoding, delimiter, "
        "header_hash, is_default, created_at, updated_at"
        ") VALUES (?,?,?,?,?,?,?,?,0,?,?)",
        (
            pid,
            user_id,
            display_name,
            json.dumps(column_map),
            sign_rule,
            encoding,
            delimiter,
            hhash,
            now,
            now,
        ),
    )
    conn.commit()
    return pid


def update_profile_column_map(
    conn: sqlite3.Connection,
    profile_id: str,
    column_map: dict[str, str],
    *,
    sign_rule: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
    headers: list[str] | None = None,
) -> bool:
    """Update an existing profile's JSON mapping."""
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT delimiter FROM csv_mapping_profiles WHERE id=?",
        (profile_id,),
    ).fetchone()
    if not row:
        return False
    delim = delimiter or row[0]
    hhash = header_row_hash(headers, delim) if headers else None
    if hhash and encoding is not None:
        conn.execute(
            "UPDATE csv_mapping_profiles SET column_map=?, sign_rule=?, "
            "encoding=?, delimiter=?, header_hash=?, updated_at=? WHERE id=?",
            (
                json.dumps(column_map),
                sign_rule,
                encoding,
                delim,
                hhash,
                now,
                profile_id,
            ),
        )
    elif hhash:
        conn.execute(
            "UPDATE csv_mapping_profiles SET column_map=?, sign_rule=?, "
            "header_hash=?, updated_at=? WHERE id=?",
            (
                json.dumps(column_map),
                sign_rule,
                hhash,
                now,
                profile_id,
            ),
        )
    else:
        conn.execute(
            "UPDATE csv_mapping_profiles SET column_map=?, sign_rule=?, "
            "updated_at=? WHERE id=?",
            (
                json.dumps(column_map),
                sign_rule,
                now,
                profile_id,
            ),
        )
    conn.commit()
    return True


def set_default_profile(conn: sqlite3.Connection, user_id: str, profile_id: str) -> None:
    conn.execute(
        "UPDATE csv_mapping_profiles SET is_default=0 WHERE user_id=?",
        (user_id,),
    )
    conn.execute(
        "UPDATE csv_mapping_profiles SET is_default=1 WHERE id=? AND user_id=?",
        (profile_id, user_id),
    )
    conn.commit()


def delete_profile(conn: sqlite3.Connection, user_id: str, profile_id: str) -> bool:
    cur = conn.execute(
        "DELETE FROM csv_mapping_profiles WHERE id=? AND user_id=?",
        (profile_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0

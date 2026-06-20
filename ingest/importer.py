"""
Orchestrate CSV file import: batches, dedupe fingerprints, balance reconciliation.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite3
import pandas as pd

from ingest.csv_detect import (
    MappingAmbiguity,
    ResolvedColumnMapping,
    detect_mapping,
    header_row_hash,
    parse_header_row,
    sniff_csv_text,
    strip_sep_hint,
)
from ingest.csv_normalize import (
    normalize_currency,
    parse_date_to_utc,
    signed_amount_from_row,
)
from . import profiles


def content_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def row_fingerprint(ts: datetime, amount: float, merchant: str) -> str:
    """Deterministic dedupe key for a logical bank row."""
    iso = ts.astimezone(timezone.utc).date().isoformat()
    norm = f"{iso}|{round(amount, 2):.2f}|{merchant.strip().lower()}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


@dataclass
class ImportResult:
    """Outcome for one CSV file."""

    path: str
    skipped: bool
    message: str
    batch_id: str | None = None
    rows_inserted: int = 0
    rows_skipped_duplicate: int = 0
    rows_skipped_invalid: int = 0
    warnings: list[str] = field(default_factory=list)


def _read_file_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _rows_from_csv(
    raw: bytes, encoding: str, delimiter: str, header_row_idx: int = 0
) -> tuple[list[str], list[dict[str, str]]]:
    """Parse CSV bytes into (headers, rows) using pandas.

    *header_row_idx* tells pandas which line is the header, letting it skip
    any number of bank-specific metadata rows automatically.
    """
    text = raw.decode(encoding, errors="replace")
    if not text.strip():
        return [], []
    df = pd.read_csv(
        io.StringIO(text),
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
        on_bad_lines="skip",
        header=header_row_idx,
    )
    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna("")
    headers = list(df.columns)
    rows = df.to_dict(orient="records")
    return headers, rows  # type: ignore[return-value]


def preview_csv_file(path: Path) -> dict[str, Any]:
    """Load headers, sniff encoding/delimiter, run auto-detect (no DB)."""
    raw = _read_file_bytes(path)
    headers, enc, delim, header_idx = parse_header_row(raw)
    # Read a generous sample to let detect_mapping disambiguate sign_rule from data.
    _, all_rows = _rows_from_csv(raw, enc, delim, header_idx)
    sample_rows = all_rows[:20]
    detected = detect_mapping(headers, encoding=enc, delimiter=delim, sample_rows=sample_rows)
    return {
        "path": str(path),
        "headers": headers,
        "encoding": enc,
        "delimiter": delim,
        "header_row_index": header_idx,
        "header_hash": header_row_hash(headers, delim),
        "detection": detected,
        "sample_rows": all_rows[:5],
    }


def import_csv_files(
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
    paths: list[Path],
    *,
    mapping: ResolvedColumnMapping | None = None,
    profile_id: str | None = None,
    force_reimport: bool = False,
    max_rows: int = 50_000,
) -> list[ImportResult]:
    """Import one or more CSV paths into ``transactions`` for *account_id*."""
    results: list[ImportResult] = []
    for path in paths:
        path = path.resolve()
        if not path.is_file():
            results.append(
                ImportResult(str(path), True, f"not a file: {path}")
            )
            continue
        raw = _read_file_bytes(path)
        csha = content_sha256(raw)
        if not force_reimport:
            row = conn.execute(
                "SELECT id FROM import_batches WHERE user_id=? AND source_path=? "
                "AND content_sha256=? AND status='completed' LIMIT 1",
                (user_id, str(path), csha),
            ).fetchone()
            if row:
                results.append(
                    ImportResult(
                        str(path),
                        True,
                        "unchanged file already imported (use force to re-import)",
                    )
                )
                continue

        headers, enc, delim, header_idx = parse_header_row(raw)

        resolved: ResolvedColumnMapping | None = mapping
        used_profile: str | None = None

        if resolved is None and profile_id:
            p = profiles.get_profile(conn, profile_id)
            if p and p["user_id"] == user_id:
                resolved = ResolvedColumnMapping(
                    column_map=p["column_map"],
                    sign_rule=p["sign_rule"] or "single_amount",
                    encoding=p["encoding"] or enc,
                    delimiter=p["delimiter"] or delim,
                )
                used_profile = profile_id

        if resolved is None:
            hh = header_row_hash(headers, delim)
            p2 = profiles.find_profile_by_header_hash(conn, user_id, hh)
            if p2:
                resolved = ResolvedColumnMapping(
                    column_map=p2["column_map"],
                    sign_rule=p2["sign_rule"] or "single_amount",
                    encoding=p2["encoding"] or enc,
                    delimiter=p2["delimiter"] or delim,
                )
                used_profile = p2["id"]

        if resolved is None:
            _, sample_rows_for_detect = _rows_from_csv(raw, enc, delim, header_idx)
            det = detect_mapping(
                headers,
                encoding=enc,
                delimiter=delim,
                sample_rows=sample_rows_for_detect[:20],
            )
            if isinstance(det, MappingAmbiguity):
                results.append(
                    ImportResult(
                        str(path),
                        True,
                        f"ambiguous mapping: {det.message}",
                    )
                )
                continue
            resolved = det

        _, data_rows = _rows_from_csv(raw, resolved.encoding, resolved.delimiter, header_idx)
        batch_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO import_batches("
            "id, user_id, source_path, content_sha256, mapping_profile_id, "
            "imported_at, row_count, skipped_duplicate_count, status"
            ") VALUES (?,?,?,?,?,?,0,0,'partial')",
            (
                batch_id,
                user_id,
                str(path),
                csha,
                used_profile,
                now_iso,
            ),
        )

        inserted = 0
        skipped_dup = 0
        skipped_bad = 0
        skipped_pending = 0
        warns: list[str] = []
        income_seen = False

        for i, row in enumerate(data_rows):
            if i >= max_rows:
                warns.append(f"stopped after {max_rows} rows (row cap)")
                break

            date_raw = row.get(resolved.column_map.get("date", ""), "")
            ts = parse_date_to_utc(date_raw)
            if ts is None:
                # Empty date in debit_credit mode = pending transaction (not yet booked)
                if not date_raw.strip() and resolved.sign_rule == "debit_credit":
                    skipped_pending += 1
                skipped_bad += 1
                continue

            amt = signed_amount_from_row(row, resolved.column_map, resolved.sign_rule)
            if amt is None or amt == 0.0:
                if amt is None and resolved.sign_rule == "debit_credit":
                    skipped_pending += 1
                skipped_bad += 1
                continue

            merch_key = resolved.column_map.get("merchant", "")
            merchant = str(row.get(merch_key, "")).strip() or "(no description)"
            # For credit-card exports (single_amount_flipped) the Amount column is
            # already the CHF-billed amount regardless of the original-currency column.
            # Skip the currency filter so foreign-currency charges aren't lost.
            if resolved.sign_rule != "single_amount_flipped":
                ccy = normalize_currency(row, resolved.column_map)
                if ccy != "CHF":
                    warns.append(f"non-CHF row skipped ({ccy}): {merchant[:40]}")
                    skipped_bad += 1
                    continue

            if amt > 0:
                income_seen = True

            fp = row_fingerprint(ts, amt, merchant)
            exists = conn.execute(
                "SELECT 1 FROM transactions WHERE account_id=? AND external_fingerprint=?",
                (account_id, fp),
            ).fetchone()
            if exists:
                skipped_dup += 1
                continue

            tid = f"csv-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO transactions("
                "id, account_id, amount, currency, merchant, category, line_category, "
                "ts, import_batch_id, external_fingerprint"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    tid,
                    account_id,
                    round(amt, 2),
                    "CHF",
                    merchant,
                    None,
                    None,
                    ts.isoformat(),
                    batch_id,
                    fp,
                ),
            )
            inserted += 1

        bal = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id=?",
            (account_id,),
        ).fetchone()[0]
        conn.execute("UPDATE accounts SET balance=? WHERE id=?", (bal, account_id))

        conn.execute(
            "UPDATE import_batches SET row_count=?, skipped_duplicate_count=?, "
            "status=? WHERE id=?",
            (inserted, skipped_dup, "completed", batch_id),
        )
        conn.commit()

        if skipped_pending:
            warns.append(
                f"{skipped_pending} pending transaction(s) skipped "
                "(Debit/Credit empty — not yet settled in CHF). "
                "They will appear once booked."
            )

        if not income_seen and inserted:
            warns.append(
                "No positive (income) rows in this file — compute_split may fail "
                "until salary/deposits are present."
            )

        results.append(
            ImportResult(
                str(path),
                False,
                "ok",
                batch_id=batch_id,
                rows_inserted=inserted,
                rows_skipped_duplicate=skipped_dup,
                rows_skipped_invalid=skipped_bad,
                warnings=warns,
            )
        )
    return results


def rollback_import_batch(
    conn: sqlite3.Connection, user_id: str, account_id: str, batch_id: str
) -> tuple[bool, str]:
    """Delete transactions for batch and mark batch rolled back; rebalance account."""
    row = conn.execute(
        "SELECT 1 FROM import_batches WHERE id=? AND user_id=?",
        (batch_id, user_id),
    ).fetchone()
    if not row:
        return False, "batch not found"
    conn.execute(
        "DELETE FROM category_proposals WHERE txn_id IN ("
        "SELECT id FROM transactions WHERE import_batch_id=? AND account_id=?)",
        (batch_id, account_id),
    )
    conn.execute(
        "DELETE FROM transactions WHERE import_batch_id=? AND account_id=?",
        (batch_id, account_id),
    )
    conn.execute(
        "UPDATE import_batches SET status='rolled_back' WHERE id=?",
        (batch_id,),
    )
    bal = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id=?",
        (account_id,),
    ).fetchone()[0]
    conn.execute("UPDATE accounts SET balance=? WHERE id=?", (bal, account_id))
    conn.commit()
    return True, "rolled back"

"""
Deterministic CSV header detection: score columns against alias tables.

Maps logical Lucid fields to the exact CSV header string. Reports ambiguity
instead of guessing when scores tie or required fields are missing.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

import chardet


class LucidField(str, Enum):
    """Logical columns required or optional for ledger import."""

    DATE = "date"
    AMOUNT = "amount"
    MERCHANT = "merchant"
    DEBIT = "debit"
    CREDIT = "credit"
    REFERENCE = "reference"
    CURRENCY = "currency"
    CATEGORY = "category"


# (pattern substring, weight) — checked on normalized header (lower, stripped)
_DATE_ALIASES: Final[list[tuple[str, float]]] = [
    ("buchungsdatum", 1.0),
    ("valutadatum", 0.95),
    ("valuta", 0.85),
    ("booking date", 1.0),
    ("purchase date", 0.95),
    ("transaction date", 0.95),
    ("transaktionsdatum", 0.95),
    ("date", 0.7),
    ("datum", 0.75),
    ("buchung", 0.5),
    ("booked", 0.97),   # booking/settlement date — preferred over purchase date for ledger accounting
]

_AMOUNT_ALIASES: Final[list[tuple[str, float]]] = [
    ("betrag", 1.0),
    ("amount", 1.0),
    ("importo", 0.8),
    ("montant", 0.85),
    ("saldo", 0.3),
]

_DEBIT_ALIASES: Final[list[tuple[str, float]]] = [
    ("belastung", 1.0),
    ("lastschrift", 0.85),
    ("debit", 0.9),
    ("soll", 0.95),
    ("abbuchung", 0.8),
    ("ausgang", 0.75),
]

_CREDIT_ALIASES: Final[list[tuple[str, float]]] = [
    ("gutschrift", 1.0),
    ("haben", 0.95),
    ("credit", 0.9),
    ("eingang", 0.75),
    ("gutschr", 0.85),
]

_MERCHANT_ALIASES: Final[list[tuple[str, float]]] = [
    ("begünstigter", 1.0),
    ("zahlungsempfänger", 0.95),
    ("beschreibung", 0.85),
    ("verwendungszweck", 0.9),
    ("booking text", 0.92),
    ("description", 0.85),
    ("narrative", 0.80),
    ("details", 0.7),
    ("text", 0.55),
    ("payee", 0.95),
    ("merchant", 0.95),
    ("counterparty", 0.85),
    ("empfänger", 0.9),
    ("buchungstext", 0.88),
]

_REFERENCE_ALIASES: Final[list[tuple[str, float]]] = [
    ("referenz", 1.0),
    ("reference", 1.0),
    ("transaktions-nr", 0.9),
    ("transaction id", 0.85),
    ("auftragsnummer", 0.8),
]

_CURRENCY_ALIASES: Final[list[tuple[str, float]]] = [
    ("währung", 1.0),
    ("currency", 1.0),
    ("ccy", 0.7),
]

# Flat list of all alias tables — used for header-row scoring.
_ALL_FIELD_ALIASES: Final[list[list[tuple[str, float]]]] = [
    _DATE_ALIASES,
    _AMOUNT_ALIASES,
    _MERCHANT_ALIASES,
    _DEBIT_ALIASES,
    _CREDIT_ALIASES,
    _REFERENCE_ALIASES,
    _CURRENCY_ALIASES,
]


def _normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower())


def _score_column(norm: str, aliases: list[tuple[str, float]]) -> float:
    best = 0.0
    for sub, w in aliases:
        if sub in norm:
            best = max(best, w)
    return best


def _best_columns(
    headers: list[str],
    aliases: list[tuple[str, float]],
) -> tuple[list[str], float]:
    """Return all headers tying for the highest score."""
    scores: list[tuple[str, float]] = []
    for h in headers:
        s = _score_column(_normalize_header(h), aliases)
        scores.append((h, s))
    if not scores:
        return [], 0.0
    best_s = max(s for _, s in scores)
    if best_s < 0.35:
        return [], best_s
    return [h for h, s in scores if s >= best_s - 1e-6 and s == best_s], best_s


@dataclass
class MappingAmbiguity:
    """Detection could not pick a unique mapping."""

    message: str
    missing_required: list[str] = field(default_factory=list)
    tied_fields: dict[str, list[str]] = field(default_factory=dict)
    best_effort: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedColumnMapping:
    """Lucid field name -> exact CSV column header."""

    column_map: dict[str, str]
    sign_rule: str  # single_amount | debit_credit
    encoding: str
    delimiter: str
    category_col: str | None = None  # raw bank category label → stored as line_category


def header_row_hash(headers: list[str], delimiter: str) -> str:
    """Stable hash for matching saved profiles to a file's header layout."""
    raw = delimiter.join(_normalize_header(h) for h in headers)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def strip_sep_hint(text: str) -> tuple[str, int]:
    """Strip leading Excel-style 'sep=X' metadata rows (kept for backward compat).

    Returns (cleaned_text, number_of_rows_skipped).
    """
    lines = text.splitlines(keepends=True)
    skip = 0
    for line in lines:
        if re.match(r"^\s*sep\s*=", line, re.IGNORECASE):
            skip += 1
        else:
            break
    return "".join(lines[skip:]), skip


def _cell_alias_score(norm_cell: str) -> float:
    """Highest alias weight across all Lucid fields that matches this cell name."""
    best = 0.0
    for aliases in _ALL_FIELD_ALIASES:
        for sub, w in aliases:
            if sub in norm_cell:
                best = max(best, w)
    return best


def find_header_row_index(text: str, delimiter: str, max_scan: int = 15) -> int:
    """Return the 0-based line index most likely to be the CSV header row.

    Scans up to *max_scan* non-empty lines and scores each by summing the best
    alias match weight for each cell.  The row whose cells best match known
    Lucid field aliases wins — no bank-specific rules needed.

    Falls back to 0 if nothing scores above zero (unknown column names).
    """
    lines = text.splitlines()
    best_idx = 0
    best_score = -1.0

    for i, line in enumerate(lines[:max_scan]):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            cells = next(csv.reader([stripped], delimiter=delimiter))
        except Exception:
            continue
        if len(cells) < 2:
            continue
        score = sum(_cell_alias_score(_normalize_header(c)) for c in cells)
        if score > best_score:
            best_score = score
            best_idx = i

    return best_idx


def sniff_csv_text(raw: bytes) -> tuple[str, str]:
    """Return (encoding, delimiter).

    Tries UTF-8 variants first (correct for the vast majority of bank exports).
    Falls back to chardet for legacy encodings (cp1252, Latin-1, etc.).
    """
    # Prefer UTF-8 — chardet can misidentify short UTF-8 with non-ASCII chars.
    for enc in ("utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        detected = chardet.detect(raw[:32768])
        enc = detected.get("encoding") or "cp1252"
        if enc.upper() == "UTF-8-SIG":
            enc = "utf-8-sig"
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            text = raw.decode("utf-8", errors="replace")
            enc = "utf-8"

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    return enc, delim


def parse_header_row(raw: bytes) -> tuple[list[str], str, str, int]:
    """Return (headers, encoding, delimiter, header_row_index).

    *header_row_index* is the 0-based line number of the detected header in
    the decoded text.  Pass it to the importer so pandas skips the right
    number of metadata rows regardless of bank format.
    """
    enc, delim = sniff_csv_text(raw)
    text = raw.decode(enc, errors="replace")
    header_idx = find_header_row_index(text, delim)
    lines = text.splitlines()
    header_line = lines[header_idx] if header_idx < len(lines) else ""
    reader = csv.reader(io.StringIO(header_line), delimiter=delim)
    row = next(reader, [])
    headers = [c.strip() for c in row]
    while headers and headers[-1] == "":
        headers.pop()
    return headers, enc, delim, header_idx


def _pick_required(
    headers: list[str],
    aliases: list[tuple[str, float]],
) -> tuple[str | None, list[str], float]:
    """Pick unique best match; return (winner, ties, score). Ties block import."""
    bests, score = _best_columns(headers, aliases)
    if len(bests) == 1:
        return bests[0], [], score
    if len(bests) > 1:
        return None, bests, score
    return None, [], score


def _pick_optional(
    headers: list[str],
    aliases: list[tuple[str, float]],
) -> tuple[str | None, float]:
    """Pick best match for an optional field; resolve ties by shortest name."""
    bests, score = _best_columns(headers, aliases)
    if not bests:
        return None, score
    # On tie, prefer the shortest header (e.g. "Currency" over "Original currency")
    return sorted(bests, key=len)[0], score


def _detect_sign_flip(sample_rows: list[dict[str, Any]], amt_col: str) -> str:
    """Return 'single_amount_flipped' if all non-empty sample amounts are positive.

    Credit-card exports (e.g. UBS MasterCard) store charges as positive numbers.
    When Debit/Credit columns exist but are empty and the Amount column is used
    instead, all-positive samples reveal this convention — amounts must be negated
    so outflows become negative per Lucid convention.
    """
    from ingest.csv_normalize import parse_decimal  # local to avoid circular at import time

    pos = neg = 0
    for row in sample_rows:
        raw = str(row.get(amt_col, "")).strip()
        if not raw:
            continue
        v = parse_decimal(raw)
        if v is None:
            continue
        if v > 0:
            pos += 1
        elif v < 0:
            neg += 1

    if pos > 0 and neg == 0:
        return "single_amount_flipped"
    return "single_amount"


def detect_mapping(
    headers: list[str],
    *,
    encoding: str,
    delimiter: str,
    sample_rows: list[dict[str, Any]] | None = None,
) -> ResolvedColumnMapping | MappingAmbiguity:
    """Score each Lucid field; require date + merchant + (amount or debit+credit).

    When both Amount and Debit/Credit headers exist, consults sample_rows to
    pick the sign_rule that reflects which columns are actually populated.
    Optional fields (currency, reference) resolve ties silently by shortest name.
    """
    if not headers:
        return MappingAmbiguity(message="CSV has no header row.")

    date_h, date_ties, date_s = _pick_required(headers, _DATE_ALIASES)
    merch_h, merch_ties, _merch_s = _pick_required(headers, _MERCHANT_ALIASES)
    amt_h, amt_ties, amt_s = _pick_required(headers, _AMOUNT_ALIASES)
    deb_h, deb_ties, _deb_s = _pick_required(headers, _DEBIT_ALIASES)
    cred_h, cred_ties, _cred_s = _pick_required(headers, _CREDIT_ALIASES)
    ref_h, _ = _pick_optional(headers, _REFERENCE_ALIASES)
    cur_h, _ = _pick_optional(headers, _CURRENCY_ALIASES)

    tied: dict[str, list[str]] = {}
    if date_ties:
        tied["date"] = date_ties
    if merch_ties:
        tied["merchant"] = merch_ties
    if amt_ties:
        tied["amount"] = amt_ties
    if deb_ties:
        tied["debit"] = deb_ties
    if cred_ties:
        tied["credit"] = cred_ties

    missing: list[str] = []
    if date_h is None:
        missing.append("date")
    if merch_h is None:
        missing.append("merchant")

    has_dc = deb_h is not None and cred_h is not None and deb_h != cred_h
    has_amt = amt_h is not None and amt_s >= 0.35

    sign_rule: str
    if has_dc and has_amt and sample_rows:
        # Both Amount and Debit/Credit columns exist — use data to decide.
        deb_filled = sum(1 for r in sample_rows if str(r.get(deb_h, "")).strip())
        cred_filled = sum(1 for r in sample_rows if str(r.get(cred_h, "")).strip())
        if max(deb_filled, cred_filled) == 0:
            # Debit/Credit are completely empty in the sample — credit-card-only
            # export (e.g. all pending, no booked rows yet). Use Amount column and
            # detect sign convention from the data.
            sign_rule = _detect_sign_flip(sample_rows, amt_h)
        else:
            # At least some Debit or Credit values present → booked CHF amounts
            # are available. Prefer them over the local-currency Amount column.
            sign_rule = "debit_credit"
    elif has_dc:
        sign_rule = "debit_credit"
    elif has_amt:
        sign_rule = "single_amount"
    else:
        sign_rule = ""
        missing.append("amount_or_debit_credit")

    if missing or tied:
        best: dict[str, str] = {}
        if date_h:
            best["date"] = date_h
        if merch_h:
            best["merchant"] = merch_h
        if amt_h:
            best["amount"] = amt_h
        if deb_h:
            best["debit"] = deb_h
        if cred_h:
            best["credit"] = cred_h
        msg_parts = []
        if missing:
            msg_parts.append(f"missing: {', '.join(missing)}")
        if tied:
            msg_parts.append(f"ambiguous columns: {', '.join(tied)}")
        return MappingAmbiguity(
            message="; ".join(msg_parts) if msg_parts else "ambiguous mapping",
            missing_required=missing,
            tied_fields=tied,
            best_effort=best,
        )

    colmap: dict[str, str] = {
        LucidField.DATE.value: date_h,  # type: ignore[dict-item]
        LucidField.MERCHANT.value: merch_h,  # type: ignore[dict-item]
    }
    if sign_rule == "debit_credit":
        colmap[LucidField.DEBIT.value] = deb_h  # type: ignore[assignment]
        colmap[LucidField.CREDIT.value] = cred_h  # type: ignore[assignment]
    else:
        colmap[LucidField.AMOUNT.value] = amt_h  # type: ignore[assignment]
    if ref_h:
        colmap[LucidField.REFERENCE.value] = ref_h
    if cur_h:
        colmap[LucidField.CURRENCY.value] = cur_h

    return ResolvedColumnMapping(
        column_map=colmap,
        sign_rule=sign_rule,
        encoding=encoding,
        delimiter=delimiter,
    )

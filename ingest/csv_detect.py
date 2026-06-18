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
from typing import Final


class LucidField(str, Enum):
    """Logical columns required or optional for ledger import."""

    DATE = "date"
    AMOUNT = "amount"
    MERCHANT = "merchant"
    DEBIT = "debit"
    CREDIT = "credit"
    REFERENCE = "reference"
    CURRENCY = "currency"


# (pattern substring, weight) — checked on normalized header (lower, stripped)
_DATE_ALIASES: Final[list[tuple[str, float]]] = [
    ("buchungsdatum", 1.0),
    ("valutadatum", 0.95),
    ("valuta", 0.85),
    ("booking date", 1.0),
    ("transaction date", 0.95),
    ("transaktionsdatum", 0.95),
    ("date", 0.7),
    ("datum", 0.75),
    ("buchung", 0.5),
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
    ("text", 0.55),
    ("details", 0.7),
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


def header_row_hash(headers: list[str], delimiter: str) -> str:
    """Stable hash for matching saved profiles to a file's header layout."""
    raw = delimiter.join(_normalize_header(h) for h in headers)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sniff_csv_text(raw: bytes) -> tuple[str, str]:
    """Return (encoding, delimiter). Try utf-8-sig then cp1252."""
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
        enc = "utf-8"

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    return enc, delim


def parse_header_row(raw: bytes) -> tuple[list[str], str, str]:
    """Return (headers, encoding, delimiter)."""
    enc, delim = sniff_csv_text(raw)
    text = raw.decode(enc)
    first_line = text.splitlines()[0] if text else ""
    reader = csv.reader(io.StringIO(first_line), delimiter=delim)
    row = next(reader, [])
    headers = [c.strip() for c in row if c.strip() or c == ""]
    # trim empty trailing
    while headers and headers[-1] == "":
        headers.pop()
    return headers, enc, delim


def detect_mapping(
    headers: list[str],
    *,
    encoding: str,
    delimiter: str,
) -> ResolvedColumnMapping | MappingAmbiguity:
    """Score each Lucid field; require date + merchant + (amount or debit+credit)."""
    if not headers:
        return MappingAmbiguity(message="CSV has no header row.")

    def pick(_field: LucidField, aliases: list[tuple[str, float]]) -> tuple[str | None, list[str], float]:
        bests, score = _best_columns(headers, aliases)
        if len(bests) == 1:
            return bests[0], [], score
        if len(bests) > 1:
            return None, bests, score
        return None, [], score

    date_h, date_ties, date_s = pick(LucidField.DATE, _DATE_ALIASES)
    merch_h, merch_ties, _merch_s = pick(LucidField.MERCHANT, _MERCHANT_ALIASES)
    amt_h, amt_ties, amt_s = pick(LucidField.AMOUNT, _AMOUNT_ALIASES)
    deb_h, deb_ties, _deb_s = pick(LucidField.DEBIT, _DEBIT_ALIASES)
    cred_h, cred_ties, _cred_s = pick(LucidField.CREDIT, _CREDIT_ALIASES)
    ref_h, ref_ties, _ = pick(LucidField.REFERENCE, _REFERENCE_ALIASES)
    cur_h, cur_ties, _ = pick(LucidField.CURRENCY, _CURRENCY_ALIASES)

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
    if ref_ties:
        tied["reference"] = ref_ties
    if cur_ties:
        tied["currency"] = cur_ties

    missing: list[str] = []
    if date_h is None:
        missing.append("date")
    if merch_h is None:
        missing.append("merchant")

    has_dc = deb_h is not None and cred_h is not None and deb_h != cred_h
    has_amt = amt_h is not None and amt_s >= 0.35

    sign_rule: str
    if has_dc:
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
        LucidField.DATE.value: date_h,
        LucidField.MERCHANT.value: merch_h,
    }
    if sign_rule == "debit_credit":
        colmap[LucidField.DEBIT.value] = deb_h  # type: ignore[arg-type]
        colmap[LucidField.CREDIT.value] = cred_h  # type: ignore[arg-type]
    else:
        colmap[LucidField.AMOUNT.value] = amt_h  # type: ignore[arg-type]
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

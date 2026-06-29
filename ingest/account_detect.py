"""
Account type inference for CSV imports.

Heuristic-first (sign_rule + sample amounts), LLM fallback for low-confidence
cases, Rich-panel HITL confirmation. Same escalation shape as csv_mapper.py.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm.provider import LLMProvider

_VALID_TYPES = ("checking", "credit_card", "savings")

_LLM_SYSTEM = """\
You are classifying a bank CSV export for a personal finance app.
Based on the filename and sample rows, infer the account type and whether it
carries regular income (salary, wages, transfers in).

Respond with ONLY a JSON object — no explanation, no markdown fences:
{
  "account_type": "checking" | "credit_card" | "savings",
  "name": "<short display name, e.g. 'UBS Credit Card' or 'PostFinance Checking'>",
  "has_income": true | false
}

Rules:
- credit_card: all amounts are outflows (positive in the CSV, negated on import);
  no salary or large recurring inflows.
- savings: low transaction frequency, mostly inflows from checking transfers.
- checking: general-purpose; may include salary inflows.
- has_income: true only when there are large positive amounts (>500) that look
  like recurring salary or wage deposits.
"""


@dataclass
class AccountProposal:
    name: str
    account_type: str   # checking | credit_card | savings
    has_income: bool
    confidence: str     # "high" | "low"


def propose_account_heuristic(preview: dict, filename: str) -> AccountProposal:
    """Infer account type from sign_rule and sample amounts."""
    from ingest.csv_detect import ResolvedColumnMapping

    det = preview.get("detection")
    sign_rule: str = ""
    if isinstance(det, ResolvedColumnMapping):
        sign_rule = det.sign_rule or ""

    sample_rows: list[dict] = preview.get("sample_rows", [])

    # Collect numeric amounts from the first available amount-like column.
    amounts: list[float] = []
    amt_keys = ("Amount", "Betrag", "amount", "Debit", "Credit")
    for row in sample_rows[:20]:
        for k in amt_keys:
            if k in row:
                try:
                    amounts.append(float(str(row[k]).replace("'", "").replace(",", ".")))
                except ValueError:
                    pass
                break

    stem = Path(filename).stem

    # Credit card: all-outflow sign rule OR all samples are non-negative
    # (credit card CSVs often export spend as positive, flipped on import).
    if sign_rule == "single_amount_flipped" or (
        amounts and all(a >= 0 for a in amounts)
    ):
        return AccountProposal(
            name=_infer_name(stem, "credit_card"),
            account_type="credit_card",
            has_income=False,
            confidence="high",
        )

    # Checking with income: any large positive amount suggests salary deposit.
    has_income = any(a > 1000 for a in amounts)
    if has_income:
        return AccountProposal(
            name=_infer_name(stem, "checking"),
            account_type="checking",
            has_income=True,
            confidence="high",
        )

    # Low confidence — hand off to LLM.
    return AccountProposal(
        name=_infer_name(stem, "checking"),
        account_type="checking",
        has_income=False,
        confidence="low",
    )


def _infer_name(stem: str, account_type: str) -> str:
    """Turn a filename stem into a readable display name."""
    readable = stem.replace("_", " ").replace("-", " ").strip().title()
    if not readable:
        return "Credit Card" if account_type == "credit_card" else "Checking"
    return readable


def propose_account_with_llm(
    llm: "LLMProvider",
    preview: dict,
    heuristic: AccountProposal,
    filename: str,
) -> AccountProposal:
    """LLM fallback for low-confidence heuristic results. Returns heuristic on failure."""
    sample_rows: list[dict] = preview.get("sample_rows", [])
    headers: list[str] = preview.get("headers", [])

    sample_text = f"Filename: {filename}\nHeaders: {headers}\n\nSample rows (up to 10):\n"
    for i, row in enumerate(sample_rows[:10]):
        sample_text += f"  Row {i + 1}: {json.dumps(row, ensure_ascii=False)}\n"

    try:
        resp = llm.complete(
            system=_LLM_SYSTEM,
            messages=[{"role": "user", "content": sample_text}],
        )
        raw = (resp.content or "").strip()
        if raw.startswith("```"):
            raw = "\n".join(
                line for line in raw.splitlines() if not line.startswith("```")
            ).strip()
        data: dict = json.loads(raw)
        account_type = data.get("account_type", "checking")
        if account_type not in _VALID_TYPES:
            account_type = "checking"
        return AccountProposal(
            name=data.get("name") or heuristic.name,
            account_type=account_type,
            has_income=bool(data.get("has_income", False)),
            confidence="high",
        )
    except Exception:
        return heuristic


def confirm_account_hitl(
    console,
    proposal: AccountProposal,
    conn: sqlite3.Connection,
    user_id: str,
) -> tuple[str, AccountProposal] | None:
    """Show Rich panel, let user edit, upsert account row. Returns (account_id, confirmed) or None."""
    from rich.panel import Panel
    from rich.table import Table
    from ingest.accounts import upsert_account

    # Show existing accounts for reference.
    rows = conn.execute(
        "SELECT name, account_type, has_income FROM accounts WHERE user_id=?",
        (user_id,),
    ).fetchall()

    if rows:
        tbl = Table(title="Existing accounts", box=None, show_header=True, padding=(0, 1))
        tbl.add_column("Name")
        tbl.add_column("Type")
        tbl.add_column("Income")
        for r in rows:
            tbl.add_row(r[0], r[1] or "checking", "yes" if r[2] else "no")
        console.print(tbl)

    # Show proposal.
    console.print(
        Panel(
            f"  Name:    [bold]{proposal.name}[/bold]\n"
            f"  Type:    [bold]{proposal.account_type}[/bold]\n"
            f"  Income:  [bold]{'yes' if proposal.has_income else 'no'}[/bold]"
            + (f"\n  [dim](confidence: {proposal.confidence})[/dim]" if proposal.confidence == "low" else ""),
            title="[bold]Proposed account[/bold]",
            border_style="cyan",
        )
    )

    # Prompt for edits — income-bearing is always assumed true.
    try:
        name_in = console.input(
            f"  Account name [[bold]{proposal.name}[/bold]]: "
        ).strip()
        name = name_in or proposal.name

        type_in = console.input(
            f"  Type (checking/credit_card/savings) [[bold]{proposal.account_type}[/bold]]: "
        ).strip().lower()
        account_type = type_in if type_in in _VALID_TYPES else proposal.account_type

    except (EOFError, KeyboardInterrupt):
        console.print("  [dim]Account selection cancelled.[/dim]")
        return None

    confirmed = AccountProposal(
        name=name, account_type=account_type, has_income=True, confidence="high"
    )
    account_id = upsert_account(conn, user_id, name, account_type, has_income=True)
    return account_id, confirmed


def detect_and_confirm_account(
    console,
    llm: "LLMProvider | None",
    preview: dict,
    conn: sqlite3.Connection,
    user_id: str,
    filename: str,
) -> str | None:
    """Full pipeline: heuristic → LLM → HITL. Returns account_id or None to skip."""
    proposal = propose_account_heuristic(preview, filename)
    if proposal.confidence == "low" and llm is not None:
        proposal = propose_account_with_llm(llm, preview, proposal, filename)
    result = confirm_account_hitl(console, proposal, conn, user_id)
    if result is None:
        return None
    account_id, _ = result
    return account_id

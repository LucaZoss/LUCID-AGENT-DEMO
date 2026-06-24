"""
Ledger categorization agent — separate from the budgeting router.

Uses ``LLMProvider`` with a narrow system prompt and a single
propose_normalized_category tool that maps to the canonical taxonomy.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import ledger_tools
from categories import ALL_KEYS_SORTED
from categories_mapping import map_from_line_category, map_from_merchant_key
from llm.provider import LLMProvider, ToolCall

_LEDGER_SYSTEM = (
    "You are a ledger tagging assistant for personal finance in Switzerland. "
    "Your ONLY job is to classify each bank transaction into ONE normalized category "
    "using the propose_normalized_category tool. "
    "You MUST call the tool for every transaction — never invent JSON or skip rows. "
    "Do NOT discuss budgets, goals, or financial advice. "
    "\n\nTaxonomy:\n"
    "  Expenses / Needs:  rent, health_insurance, groceries_food, telecom\n"
    "  Expenses / Wants:  car, clothing, digital_goods, health_other, housing, "
    "restaurants, sports, travel_holidays, transport, wellbeing, wants_other\n"
    "  Income:            salary\n"
    "  Extras:            twint_credit (positive Twint transfers), "
    "twint_debit (negative Twint transfers), extras_other\n"
    "\nClassify income rows (positive amount) as 'salary' unless they look like "
    "a Twint transfer — then use 'twint_credit'."
)

_LEDGER_TOOLS_V2: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "propose_normalized_category",
            "description": (
                "Record a proposed normalized category for one transaction. "
                "Pick exactly one key from the taxonomy enum."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "txn_id": {"type": "string"},
                    "merchant": {"type": "string"},
                    "proposed_normalized": {
                        "type": "string",
                        "enum": ALL_KEYS_SORTED,
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["txn_id", "merchant", "proposed_normalized"],
            },
        },
    },
]

# Legacy tool list kept so run_ledger_categorizer_legacy can still be called
# by tests or external code that hasn't migrated yet.
_LEDGER_TOOLS: list[dict[str, Any]] = _LEDGER_TOOLS_V2


def _fetch_uncategorized(
    conn: sqlite3.Connection, user_id: str, limit: int
) -> list[dict[str, Any]]:
    """Return transactions (any sign) that have no normalized_category yet."""
    rows = conn.execute(
        "SELECT t.id, t.merchant, t.amount, t.ts, t.line_category FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.normalized_category IS NULL "
        "ORDER BY t.ts DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [
        {
            "txn_id": r[0],
            "merchant": r[1],
            "amount": r[2],
            "ts": r[3],
            "line_category": r[4],
        }
        for r in rows
    ]


# Keep old name as alias so existing callers don't break
def _fetch_uncategorized_outflows(
    conn: sqlite3.Connection, user_id: str, limit: int
) -> list[dict[str, Any]]:
    return _fetch_uncategorized(conn, user_id, limit)


def _dispatch_tool(
    name: str,
    args: dict[str, Any],
    conn: sqlite3.Connection,
    user_id: str,
) -> dict[str, Any]:
    if name == "propose_normalized_category":
        return ledger_tools.propose_normalized_category(
            conn,
            user_id,
            str(args.get("txn_id", "")),
            str(args.get("merchant", "")),
            str(args.get("proposed_normalized", "")),
            rationale=str(args.get("rationale", "")),
        )
    # Legacy stubs — still work for any external callers
    if name == "propose_spending_bucket":
        return ledger_tools.propose_spending_bucket(
            conn,
            user_id,
            str(args.get("txn_id", "")),
            str(args.get("merchant", "")),
            str(args.get("proposed_bucket", "")),
            rationale=str(args.get("rationale", "")),
        )
    if name == "propose_line_category":
        return ledger_tools.propose_line_category(
            conn,
            user_id,
            str(args.get("txn_id", "")),
            str(args.get("merchant", "")),
            str(args.get("proposed_line", "")),
            rationale=str(args.get("rationale", "")),
        )
    return {"ok": False, "error": f"unknown tool {name}"}


def _tc_to_openai_dict(tc: ToolCall) -> dict[str, Any]:
    return {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
    }


def _load_merchant_overrides(
    conn: sqlite3.Connection, user_id: str
) -> dict[str, tuple[str | None, str | None, str | None]]:
    """Return {merchant_normalized: (bucket, line_category, normalized_category)}."""
    rows = conn.execute(
        "SELECT merchant_normalized, bucket, line_category, normalized_category "
        "FROM merchant_category_overrides WHERE user_id=?",
        (user_id,),
    ).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _pre_fill_deterministic(
    conn: sqlite3.Connection,
    user_id: str,
    txns: list[dict[str, Any]],
    overrides: dict[str, tuple[str | None, str | None, str | None]],
) -> tuple[list[dict[str, Any]], int]:
    """Pre-fill proposals deterministically and return remaining unknowns + count."""
    unknown_txns: list[dict[str, Any]] = []
    pre_filled = 0

    for t in txns:
        merchant_key = t["merchant"].lower().strip()
        norm_key: str | None = None

        # 1. Check merchant memory (highest priority — user-confirmed)
        if merchant_key in overrides:
            _, _, mem_norm = overrides[merchant_key]
            if mem_norm:
                norm_key = mem_norm
            else:
                # Derive from legacy line_category in override
                _, mem_line, _ = overrides[merchant_key]
                norm_key = map_from_line_category(mem_line) if mem_line else None

        # 2. Try line_category mapping (already assigned by Labeller)
        if not norm_key:
            norm_key = map_from_line_category(t.get("line_category"))

        # 3. Merchant pattern lookup
        if not norm_key:
            norm_key = map_from_merchant_key(merchant_key)
            # Refine twint direction by amount sign
            if norm_key == "twint_debit" and (t.get("amount") or 0) > 0:
                norm_key = "twint_credit"

        # 4. Salary heuristic: positive amount with no match → salary
        if not norm_key and (t.get("amount") or 0) > 0:
            norm_key = "salary"

        if norm_key:
            ledger_tools.propose_normalized_category(
                conn, user_id, t["txn_id"], t["merchant"], norm_key,
                rationale="deterministic",
            )
            pre_filled += 1
        else:
            unknown_txns.append(t)

    return unknown_txns, pre_filled


def run_ledger_categorizer_legacy(
    llm: LLMProvider,
    conn: sqlite3.Connection,
    user_id: str,
    *,
    batch_limit: int = 15,
    max_iterations: int = 8,
) -> str:
    """LLM-only categorizer (no HITL). Pre-fills deterministically where possible."""
    txns = _fetch_uncategorized(conn, user_id, batch_limit)
    if not txns:
        return "No uncategorized transactions to process."

    overrides = _load_merchant_overrides(conn, user_id)
    unknown_txns, pre_filled = _pre_fill_deterministic(conn, user_id, txns, overrides)

    if not unknown_txns:
        return f"All {pre_filled} transaction(s) pre-filled deterministically."

    lines = "\n".join(
        f"- id={t['txn_id']} merchant={t['merchant']!r} amount={t['amount']} ts={t['ts']}"
        for t in unknown_txns
    )
    user_block = (
        "Classify each transaction below using propose_normalized_category. "
        "Use exactly one taxonomy key per transaction.\n\n"
        f"{lines}"
    )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_block},
    ]

    for _ in range(max_iterations):
        resp = llm.complete(
            system=_LEDGER_SYSTEM,
            messages=messages,
            tools=_LEDGER_TOOLS_V2,
        )
        if resp.stop_reason == "end_turn" or not resp.tool_calls:
            summary = resp.content or "Done (no further tool calls)."
            if pre_filled:
                summary = f"{pre_filled} pre-filled deterministically. " + summary
            return summary

        messages.append({
            "role": "assistant",
            "content": resp.content,
            "tool_calls": [_tc_to_openai_dict(tc) for tc in resp.tool_calls],
        })

        for tc in resp.tool_calls:
            result = _dispatch_tool(tc.name, tc.arguments, conn, user_id)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    suffix = f" ({pre_filled} pre-filled deterministically)" if pre_filled else ""
    return f"(ledger categorizer reached iteration limit){suffix}"


def run_ledger_categorizer(
    llm: LLMProvider,
    conn: sqlite3.Connection,
    user_id: str,
    *,
    batch_limit: int = 15,
    max_iterations: int = 8,
    console=None,
) -> str:
    """Entry point for /cat-run REPL command.

    When *console* is provided, delegates to the Labeller Agent (HITL).
    Otherwise falls back to the legacy LLM-only categorizer for headless use.
    """
    if console is not None:
        from agents.labeller.agent import run_labeller_agent
        return run_labeller_agent(
            llm, conn, user_id, console,
            batch_limit=batch_limit,
            max_iterations=max_iterations,
        )
    return run_ledger_categorizer_legacy(
        llm, conn, user_id,
        batch_limit=batch_limit,
        max_iterations=max_iterations,
    )

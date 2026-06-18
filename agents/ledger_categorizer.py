"""
Ledger categorization agent — separate from the budgeting router.

Uses ``LLMProvider`` with a narrow system prompt and two proposal tools only.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import ledger_tools
from llm.provider import LLMProvider, ToolCall

_LEDGER_SYSTEM = (
    "You are a ledger tagging assistant. Your ONLY job is to classify bank "
    "transactions for bookkeeping: spending bucket (need/want/savings) and "
    "optional fine line category (rent, groceries, …). "
    "You MUST call the provided tools to record proposals — never invent JSON. "
    "Do NOT discuss budgets, goals, or financial advice. "
    "If a transaction is income (positive amount), skip it."
)

_LEDGER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "propose_spending_bucket",
            "description": (
                "Record a proposed need/want/savings bucket for one outflow transaction."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "txn_id": {"type": "string"},
                    "merchant": {"type": "string"},
                    "proposed_bucket": {
                        "type": "string",
                        "enum": ["need", "want", "savings"],
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["txn_id", "merchant", "proposed_bucket"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_line_category",
            "description": (
                "Record a proposed fine-grained category (rent, health_insurance, …)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "txn_id": {"type": "string"},
                    "merchant": {"type": "string"},
                    "proposed_line": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["txn_id", "merchant", "proposed_line"],
            },
        },
    },
]


def _fetch_uncategorized_outflows(
    conn: sqlite3.Connection, user_id: str, limit: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT t.id, t.merchant, t.amount, t.ts FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.amount < 0 AND t.category IS NULL "
        "ORDER BY t.ts DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [
        {
            "txn_id": r[0],
            "merchant": r[1],
            "amount": r[2],
            "ts": r[3],
        }
        for r in rows
    ]


def _dispatch_tool(
    name: str,
    args: dict[str, Any],
    conn: sqlite3.Connection,
    user_id: str,
) -> dict[str, Any]:
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


def run_ledger_categorizer(
    llm: LLMProvider,
    conn: sqlite3.Connection,
    user_id: str,
    *,
    batch_limit: int = 15,
    max_iterations: int = 8,
) -> str:
    """Propose categories for a batch of uncategorized outflows; returns summary text."""
    txns = _fetch_uncategorized_outflows(conn, user_id, batch_limit)
    if not txns:
        return "No uncategorized outflow transactions to process."

    lines = "\n".join(
        f"- id={t['txn_id']} merchant={t['merchant']!r} amount={t['amount']} ts={t['ts']}"
        for t in txns
    )
    user_block = (
        "Classify each transaction below. For each one, call propose_spending_bucket "
        "with a valid bucket, then propose_line_category with a valid line label.\n\n"
        f"{lines}"
    )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_block},
    ]

    for _ in range(max_iterations):
        resp = llm.complete(
            system=_LEDGER_SYSTEM,
            messages=messages,
            tools=_LEDGER_TOOLS,
        )
        if resp.stop_reason == "end_turn" or not resp.tool_calls:
            summary = resp.content or "Done (no further tool calls)."
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

    return "(ledger categorizer reached iteration limit)"

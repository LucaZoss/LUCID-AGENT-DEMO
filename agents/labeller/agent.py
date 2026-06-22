"""
Labeller Agent — Agent 2 in the refactored LUCID pipeline.

Steps:
  1. fetch_unlabelled → batch of uncategorized outflow transactions
  2. For each: lookup_merchant_memory → check if we know this merchant
  3. propose_clean_name + propose_bucket for all transactions
  4. Tier by confidence: auto-apply (known, user_confirmed, high confidence) vs. needs review
  5. batch_confirm_with_user → HITL confirmation table
  6. apply_labels → UPDATE transactions + UPSERT merchant_category_overrides

Usage:
    from agents.labeller.agent import run_labeller_agent
    summary = run_labeller_agent(llm, conn, user_id, console)
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from llm.provider import LLMProvider, ToolCall

from agents.labeller import tools as _tools

_SYSTEM = """\
You are the Labeller Agent for LUCID personal finance.
Your job: clean merchant names and classify transactions into need/want/savings buckets.

Follow these steps:

1. Call fetch_unlabelled to get uncategorized outflow transactions.
2. For each transaction: call lookup_merchant_memory to check the merchant override table.
3. For transactions not in memory: call propose_clean_name and propose_bucket.
4. Call batch_confirm_with_user with all transactions (auto-apply high-confidence known merchants, show table for new ones).
5. Call apply_labels with the confirmed results.
6. Report a brief summary to the user.

Rules:
- Keep messages short; this is a terminal UI.
- Never guess buckets — use the tools.
- Income transactions (positive amount) are already excluded by fetch_unlabelled.
- Do not discuss budgets or goals — that is the REPL's job.
"""

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fetch_unlabelled",
            "description": "Return outflow transactions without clean_name or category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max transactions to process (default 50).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_merchant_memory",
            "description": "Check if a merchant is in the override table with a known clean name and bucket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant": {"type": "string"}
                },
                "required": ["merchant"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_clean_name",
            "description": "Return the deterministic cleaned merchant name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant": {"type": "string"}
                },
                "required": ["merchant"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_bucket",
            "description": "Return the proposed need/want/savings bucket and confidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant": {"type": "string"},
                    "amount": {"type": "number"},
                    "sector_hint": {
                        "type": "string",
                        "description": "Raw bank category label from CSV (optional).",
                    },
                },
                "required": ["merchant", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_confirm_with_user",
            "description": (
                "Show tiered confirmation UI: auto-apply known confirmed merchants, "
                "display review table for new/low-confidence ones. Returns confirmed labels."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "transactions": {
                        "type": "array",
                        "description": (
                            "List of transaction dicts, each with: txn_id, merchant, "
                            "amount, clean_name, proposed_bucket, confidence, "
                            "auto_apply (bool), sector_hint (optional)."
                        ),
                        "items": {"type": "object"},
                    }
                },
                "required": ["transactions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_labels",
            "description": "Write confirmed clean_name + category to transactions; update merchant memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {
                        "type": "array",
                        "description": "List from batch_confirm_with_user: [{txn_id, clean_name, bucket, source}]",
                        "items": {"type": "object"},
                    }
                },
                "required": ["confirmed"],
            },
        },
    },
]


def _tc_to_openai_dict(tc: ToolCall) -> dict[str, Any]:
    return {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
    }


def _dispatch_tool(
    name: str,
    args: dict[str, Any],
    conn: sqlite3.Connection,
    user_id: str,
    console,
    # merchant_raw_map shared across the agent run so apply_labels can look up raw names
    merchant_raw_map: dict[str, str],
) -> Any:
    if name == "fetch_unlabelled":
        result = _tools.fetch_unlabelled(conn, user_id, int(args.get("limit", 50)))
        # Build raw merchant map for later apply_labels call
        for t in result.get("transactions", []):
            merchant_raw_map[t["txn_id"]] = t["merchant"]
        return result

    if name == "lookup_merchant_memory":
        return _tools.lookup_merchant_memory(conn, user_id, str(args.get("merchant", "")))

    if name == "propose_clean_name":
        return _tools.propose_clean_name(str(args.get("merchant", "")))

    if name == "propose_bucket":
        return _tools.propose_bucket(
            str(args.get("merchant", "")),
            float(args.get("amount", 0.0)),
            sector_hint=args.get("sector_hint") or None,
        )

    if name == "batch_confirm_with_user":
        txns = list(args.get("transactions") or [])
        return _tools.batch_confirm_with_user(txns, console)

    if name == "apply_labels":
        confirmed = list(args.get("confirmed") or [])
        return _tools.apply_labels(conn, user_id, confirmed, merchant_raw_map)

    return {"ok": False, "error": f"unknown tool: {name}"}


def run_labeller_agent(
    llm: LLMProvider,
    conn: sqlite3.Connection,
    user_id: str,
    console,
    *,
    batch_limit: int = 50,
    max_iterations: int = 30,
) -> str:
    """Run the Labeller Agent interactively. Returns final summary text."""
    console.print("\n[bold cyan]━━  Labeller: cleaning names & classifying  ━━[/bold cyan]")
    console.print(
        "[dim]I'll clean merchant names and classify transactions. "
        "Known merchants are auto-applied; new ones need a quick review.[/dim]\n"
    )

    merchant_raw_map: dict[str, str] = {}

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Please label up to {batch_limit} uncategorized transactions. "
                "Fetch unlabelled transactions, check merchant memory, propose clean names "
                "and buckets, confirm with me, then apply the labels."
            ),
        }
    ]

    final_text = "Labelling complete."

    for _ in range(max_iterations):
        try:
            resp = llm.complete(
                system=_SYSTEM,
                messages=messages,
                tools=_TOOLS,
            )
        except Exception as exc:
            console.print(f"\n[bold red]  Labeller: LLM error — {exc}[/bold red]")
            console.print("[dim]  Check your API key / provider and retry with /cat-run.[/dim]")
            return f"Labelling aborted: {exc}"

        if resp.content:
            console.print(
                f"\n[bold cyan]  Labeller:[/bold cyan]\n  {resp.content}"
            )
            final_text = resp.content

        if resp.stop_reason == "end_turn" or not resp.tool_calls:
            break

        messages.append({
            "role": "assistant",
            "content": resp.content,
            "tool_calls": [_tc_to_openai_dict(tc) for tc in resp.tool_calls],
        })

        for tc in resp.tool_calls:
            result = _dispatch_tool(
                tc.name, tc.arguments, conn, user_id, console, merchant_raw_map
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    return final_text

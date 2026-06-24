"""
Labeller Agent — Agent 2 in the LUCID pipeline.

Responsibility: assign a descriptive *line_category* (e.g. "Grocery Stores",
"Electronics Stores") and a clean display name to every uncategorized outflow
transaction.

It does NOT assign need/want/savings — that is the budget agent's job.

Steps:
  1. fetch_unlabelled → batch of outflows missing line_category
  2. detect_merchant_patterns → group by merchant prefix (2+ = rule candidate)
  3. For each group/transaction: lookup_merchant_memory, then propose_line_category
  4. batch_confirm_with_user → HITL table; pattern groups offer rule-saving
  5. apply_labels → UPDATE transactions (clean_name, line_category); optionally
     UPSERT merchant_category_overrides for saved rules

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
Your job: assign a normalized *line_category* key and a clean merchant name to
every uncategorized outflow transaction imported from CSV.

Use EXACTLY one of these canonical taxonomy keys for line_category:

  Expenses / Needs:   rent  health_insurance  groceries_food  telecom
  Expenses / Wants:   car  clothing  digital_goods  health_other  housing
                      restaurants  sports  travel_holidays  transport
                      wellbeing  wants_other
  Income:             salary
  Extras:             twint_credit  twint_debit  extras_other

Classification examples (use these as reference):
  Coop, Migros, Aldi, Denner → groceries_food
  Netflix, Spotify, Disney+, Adobe, GitHub, Claude.AI, Anthropic → digital_goods
  Starbucks, McDonald's, any restaurant → restaurants
  SBB, BLS, ZVV, Uber → transport
  Helsana, Swica, CSS, Assura → health_insurance
  Fitnesspark, Gym, Decathlon → sports
  Digitec, Galaxus, MediaMarkt → digital_goods

CRITICAL RULES:
- Do NOT narrate what you are about to do. Do NOT write step-by-step plans.
- Do NOT generate example merchants, example outputs, or fictional data.
- Do NOT produce any text output between tool calls.
- Call tools immediately and silently, one after another.
- Your ONLY text output is the final one-line summary after apply_labels completes
  (e.g. "Labelled 50 transactions, 3 rules saved.").
- Do NOT classify into need / want / savings. That is the budget agent's job.
- Never invent financial amounts or do arithmetic.
- When propose_line_category returns confidence=0, use your world knowledge to
  pick the best taxonomy key. Default to wants_other only when truly ambiguous.

Tool call sequence (no text between steps):
1. fetch_unlabelled
2. detect_merchant_patterns
3. For each group/single: lookup_merchant_memory, then propose_line_category, propose_clean_name
4. batch_confirm_with_user (pass ALL real transaction IDs from step 1 — never invent IDs)
5. apply_labels
6. Output one-line summary only.
"""

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fetch_unlabelled",
            "description": "Return outflow transactions without a line_category.",
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
            "name": "detect_merchant_patterns",
            "description": (
                "Group transactions by normalized merchant name. "
                "Returns patterns (2+ rows sharing a merchant prefix) — candidates "
                "for a saved rule — and singles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "transactions": {
                        "type": "array",
                        "description": "List of transaction dicts from fetch_unlabelled.",
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
            "name": "lookup_merchant_memory",
            "description": "Check the override table for a known line_category for this merchant.",
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
            "description": "Return the deterministic cleaned merchant display name.",
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
            "name": "propose_line_category",
            "description": (
                "Return a proposed normalized taxonomy key (e.g. 'restaurants', "
                "'groceries_food', 'digital_goods') for a merchant. "
                "Uses sector_hint from CSV if available, then merchant rules. "
                "Returns line_category=null when unknown — use your own judgment then, "
                "picking the best key from the canonical taxonomy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant": {"type": "string"},
                    "sector_hint": {
                        "type": "string",
                        "description": "Raw bank category label from CSV, if present.",
                    },
                },
                "required": ["merchant"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_confirm_with_user",
            "description": (
                "Show HITL confirmation UI. Pattern groups are presented once with "
                "an option to save as a rule. Auto-apply known merchants in bulk. "
                "Returns confirmed label list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "transactions": {
                        "type": "array",
                        "description": (
                            "All transactions to confirm. Each dict: txn_id, merchant, "
                            "amount, clean_name, proposed_line_category, confidence, "
                            "auto_apply (bool), sector_hint (optional), "
                            "pattern_key (optional), is_pattern_lead (optional bool)."
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
            "description": (
                "Write clean_name + line_category to transactions. "
                "When save_rule=True in a confirmed entry, also upsert "
                "merchant_category_overrides for future auto-labelling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {
                        "type": "array",
                        "description": (
                            "List from batch_confirm_with_user: "
                            "[{txn_id, clean_name, line_category, source, save_rule}]"
                        ),
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
    merchant_raw_map: dict[str, str],
) -> Any:
    if name == "fetch_unlabelled":
        result = _tools.fetch_unlabelled(conn, user_id, int(args.get("limit", 50)))
        for t in result.get("transactions", []):
            merchant_raw_map[t["txn_id"]] = t["merchant"]
        return result

    if name == "detect_merchant_patterns":
        txns = list(args.get("transactions") or [])
        return _tools.detect_merchant_patterns(txns)

    if name == "lookup_merchant_memory":
        return _tools.lookup_merchant_memory(conn, user_id, str(args.get("merchant", "")))

    if name == "propose_clean_name":
        return _tools.propose_clean_name(str(args.get("merchant", "")))

    if name == "propose_line_category":
        return _tools.propose_line_category(
            str(args.get("merchant", "")),
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
    max_iterations: int = 40,
) -> str:
    """Run the Labeller Agent interactively. Returns final summary text."""
    console.print("\n[bold cyan]━━  Labeller: categorising transactions  ━━[/bold cyan]")
    console.print(
        "[dim]I'll assign a descriptive category to each transaction. "
        "Repeated merchants can be saved as rules for future imports.[/dim]\n"
    )

    merchant_raw_map: dict[str, str] = {}

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Please categorise up to {batch_limit} uncategorised transactions. "
                "Fetch them, detect merchant patterns, look up merchant memory, "
                "propose a descriptive line_category and clean name for each, "
                "confirm with me (offering to save rules for repeated merchants), "
                "then apply the labels."
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

        is_final = resp.stop_reason == "end_turn" or not resp.tool_calls
        if resp.content and is_final:
            console.print(f"\n[bold cyan]  Labeller:[/bold cyan]\n  {resp.content}")
            final_text = resp.content

        if is_final:
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

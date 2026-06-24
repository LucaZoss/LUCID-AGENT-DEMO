"""
Router — the agent's main turn loop.

Flow per user message
---------------------
1. Cheap route call  : give the router LLM only the skill manifest + user message;
                       it returns a skill name (or "none").
2. Load skill        : read_skill(name) fetches the full SKILL.md from disk.
3. Assemble context  : context_assembler rebuilds the full system prompt + messages
                       from the authoritative DB (fresh every turn).
4. Tool-calling loop : execute skill with tool definitions wired to Phase-2 tools;
                       keep looping until stop_reason == "end_turn".
5. Persist turn      : save user + assistant messages to the DB.

The router never does arithmetic and never mutates the DB except via
_persist_turn.  State changes triggered by tool output (e.g. saving a new goal)
are the responsibility of the skill + a future persist_tool call.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import date, datetime

import tools as tools_module
from contracts import StructuredGoal, Transaction
from llm.provider import LLMProvider, ToolCall
from llm.tool_definitions import TOOL_DEFINITIONS
from orchestrator.context_assembler import assemble_context
from skills.skill_loader import list_skills, read_skill

_ROUTE_SYSTEM = (
    "You are a routing agent for a personal finance assistant. "
    "Given a list of available skills and the user's message, return ONLY the "
    "skill name exactly as listed. No explanation, no punctuation, nothing else. "
    "If no skill fits, return the word: none"
)


# ── Public API ─────────────────────────────────────────────────────────────────

def route(llm: LLMProvider, user_message: str) -> str:
    """Return the best skill name for *user_message*, or 'none'."""
    manifest = list_skills()
    skill_lines = "\n".join(
        f"- {s['name']}: {s['description']}" for s in manifest
    )
    resp = llm.complete(
        system=_ROUTE_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Skills:\n{skill_lines}\n\nUser message: {user_message}",
        }],
    )
    return (resp.content or "none").strip().lower()


def handle_message(
    llm: LLMProvider,
    conn: sqlite3.Connection,
    user_id: str,
    conversation_id: str,
    user_message: str,
) -> str:
    """Full agent turn: route → load skill → tool loop → return response text."""

    # Stage 1 — cheap routing (manifest only, no full skill instructions)
    skill_name = route(llm, user_message)
    skill_instructions = ""
    if skill_name != "none":
        try:
            skill_instructions = read_skill(skill_name)
        except FileNotFoundError:
            skill_instructions = ""

    # Stage 2 — assemble context fresh from the DB
    ctx = assemble_context(
        conn, user_id, conversation_id, user_message,
        tools=tools_module,
    )

    # Prepend full skill instructions to the system prompt when a skill matched
    system = ctx.system_prompt
    if skill_instructions:
        system = f"[SKILL: {skill_name}]\n{skill_instructions}\n\n{system}"

    # Stage 3 — tool-calling execution loop
    messages = list(ctx.messages)
    max_iterations = 10

    for _ in range(max_iterations):
        resp = llm.complete(system=system, messages=messages, tools=TOOL_DEFINITIONS)

        if resp.stop_reason == "end_turn" or not resp.tool_calls:
            final = resp.content or "(no response)"
            _persist_turn(conn, conversation_id, user_message, final)
            return final

        # Append assistant turn with tool_calls so the next iteration has history
        messages.append({
            "role": "assistant",
            "content": resp.content,
            "tool_calls": [_tc_to_openai_dict(tc) for tc in resp.tool_calls],
        })

        # Execute every tool call in this response before the next LLM call
        for tc in resp.tool_calls:
            result = _dispatch_tool(tc.name, tc.arguments, conn, user_id)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    return "(reached tool-call iteration limit)"


# ── Tool dispatch ──────────────────────────────────────────────────────────────

def _dispatch_tool(
    name: str,
    args: dict,
    conn: sqlite3.Connection,
    user_id: str,
) -> dict:
    """Map LLM tool names to deterministic Phase-2 Python functions."""

    if name == "compute_current_split":
        days = int(args.get("days", 90))
        txns = _fetch_transactions(conn, user_id, days)
        if not txns:
            return {"error": f"No transactions found in the last {days} days."}
        try:
            result = tools_module.compute_split(txns)
            return asdict(result)
        except ValueError:
            return {"error": f"No transactions found in the last {days} days."}

    if name == "get_goal_status":
        row = conn.execute(
            "SELECT id, user_id, goal_type, amount, target_date, engagement, framework, active "
            "FROM goals WHERE user_id=? AND active=1 ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            return {"goal": None, "message": "No active goal set yet."}
        goal = StructuredGoal(
            id=row[0], user_id=row[1], goal_type=row[2], amount=row[3],
            target_date=date.fromisoformat(row[4]) if row[4] else None,
            engagement=row[5], framework=row[6], active=bool(row[7]),
        )
        txns = _fetch_transactions(conn, user_id, 90)
        income = sum(t.amount for t in txns if t.amount > 0)
        current_savings = _fetch_savings_total(conn, user_id)
        try:
            feasibility = tools_module.compute_goal_feasibility(
                goal, income or 1.0, current_savings
            )
            return {"goal": asdict(goal), "feasibility": asdict(feasibility)}
        except ValueError as exc:
            return {"goal": asdict(goal), "error": str(exc)}

    if name == "get_dashboard_summary":
        period = args.get("period") or datetime.now().strftime("%Y-%m")
        txns = _fetch_transactions(conn, user_id, 31)
        if not txns:
            return {"error": "No transactions found for this period."}
        try:
            payload = tools_module.build_dashboard_payload(period, txns)
            return asdict(payload)
        except ValueError as exc:
            return {"error": str(exc)}

    if name == "categorize_merchant":
        merchant = args.get("merchant", "")
        dummy = Transaction(
            id="tmp", account_id="tmp", amount=-1.0, currency="CHF",
            merchant=merchant, category=None, ts=datetime.now(),
            line_category=None, import_batch_id=None, external_fingerprint=None,
        )
        category = tools_module.categorize_transaction(dummy)
        return {"merchant": merchant, "category": category}

    if name == "get_transactions_by_bucket":
        from db.queries import get_transactions_by_bucket
        bucket = args.get("bucket", "")
        days = int(args.get("days", 90))
        try:
            txns = get_transactions_by_bucket(conn, user_id, bucket, days=days)
            return {
                "bucket": bucket,
                "days": days,
                "count": len(txns),
                "transactions": [
                    {
                        "id": t.id,
                        "merchant": t.merchant,
                        "amount": t.amount,
                        "line_category": t.line_category,
                        "ts": t.ts.date().isoformat(),
                    }
                    for t in txns
                ],
            }
        except ValueError as exc:
            return {"error": str(exc)}

    if name == "get_transactions_by_category":
        from db.queries import get_transactions_by_line_category
        category = args.get("category", "")
        days = int(args.get("days", 90))
        try:
            txns = get_transactions_by_line_category(conn, user_id, category, days=days)
            return {
                "category": category,
                "days": days,
                "count": len(txns),
                "transactions": [
                    {
                        "id": t.id,
                        "merchant": t.merchant,
                        "amount": t.amount,
                        "bucket": t.category,
                        "ts": t.ts.date().isoformat(),
                    }
                    for t in txns
                ],
            }
        except ValueError as exc:
            return {"error": str(exc)}

    return {"error": f"Unknown tool: '{name}'"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fetch_transactions(
    conn: sqlite3.Connection, user_id: str, days: int
) -> list[Transaction]:
    rows = conn.execute(
        "SELECT t.id, t.account_id, t.amount, t.currency, t.merchant, t.category, "
        "t.line_category, t.ts, t.import_batch_id, t.external_fingerprint "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.ts >= datetime('now', ?) ORDER BY t.ts",
        (user_id, f"-{days} days"),
    ).fetchall()
    return [
        Transaction(
            id=r[0], account_id=r[1], amount=r[2], currency=r[3],
            merchant=r[4], category=r[5], line_category=r[6],
            ts=datetime.fromisoformat(r[7]),
            import_batch_id=r[8], external_fingerprint=r[9],
        )
        for r in rows
    ]


def _fetch_savings_total(conn: sqlite3.Connection, user_id: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(ABS(t.amount)), 0.0) "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.category='savings'",
        (user_id,),
    ).fetchone()
    return row[0] if row else 0.0


def _tc_to_openai_dict(tc: ToolCall) -> dict:
    return {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
    }


def _persist_turn(
    conn: sqlite3.Connection,
    conversation_id: str,
    user_msg: str,
    assistant_msg: str,
) -> None:
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO messages(id, conversation_id, role, content, ts) VALUES(?,?,?,?,?)",
        (str(uuid.uuid4()), conversation_id, "user", user_msg, now),
    )
    conn.execute(
        "INSERT INTO messages(id, conversation_id, role, content, ts) VALUES(?,?,?,?,?)",
        (str(uuid.uuid4()), conversation_id, "assistant", assistant_msg, now),
    )
    conn.commit()

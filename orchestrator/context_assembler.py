"""
Per-turn context assembler.

Rebuilds the LLM's context FRESH on every turn from the authoritative DB stores
+ live tool output. This is the heart of the memory model in CLAUDE.md:

    structured state lives in the DB and is authoritative;
    LLM context is a derived, lossy view assembled per request.

The assembler never trusts conversation history for FACTS — goal/budget come
from rows, current numbers come from tools run fresh, and only the *dialogue*
comes from the message log (recent verbatim + older compressed into a summary).

This is framework-agnostic: it returns a (system_prompt, messages) pair your
LLMProvider adapter can hand to any vendor.
"""

import json
from dataclasses import dataclass
from datetime import datetime

from contracts import StructuredGoal, Transaction

# Tunables — how much verbatim dialogue to keep before relying on the summary.
RECENT_TURNS = 8


@dataclass
class AssembledContext:
    system_prompt: str
    messages: list[dict]   # [{role, content}, ...] ready for LLMProvider.complete


def assemble_context(
    conn,
    user_id: str,
    conversation_id: str,
    user_message: str,
    *,
    tools,                 # the deterministic tools module (run fresh each turn)
    persona: str = "neutral",
    rag_retrieve=None,     # optional callable(user_id, query)->list[str]; DEFERRED
) -> AssembledContext:

    profile = _load_profile(conn, user_id)              # Layer 1: durable facts
    snapshot = _live_snapshot(conn, user_id, tools)     # Layer 2: FRESH numbers
    summary = _load_summary(conn, user_id)              # Layer 3: compressed
    recent = _recent_turns(conn, conversation_id)       # Layer 3: verbatim

    system = _build_system_prompt(persona, profile, snapshot, summary)

    messages: list[dict] = []

    # Optional long-term recall — deferred for the demo, wired but off by default.
    if rag_retrieve is not None:
        notes = rag_retrieve(user_id, user_message)
        if notes:
            joined = "\n".join(f"- {n}" for n in notes)
            messages.append({
                "role": "user",
                "content": f"[relevant past notes]\n{joined}",
            })

    messages.extend(recent)                             # last N verbatim turns
    messages.append({"role": "user", "content": user_message})

    return AssembledContext(system_prompt=system, messages=messages)


# ── Layer 1: durable facts straight from the DB ────────────────────────────
def _load_profile(conn, user_id: str) -> dict:
    goal = conn.execute(
        "SELECT goal_type, amount, target_date, engagement, framework "
        "FROM goals WHERE user_id=? AND active=1 ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    budget = conn.execute(
        "SELECT allocations, target_ratios, period FROM budgets "
        "WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    prefs = conn.execute(
        "SELECT quiet_hours, max_pushes_day, digest_time, persona "
        "FROM prefs WHERE user_id=?",
        (user_id,),
    ).fetchone()

    return {"goal": goal, "budget": budget, "prefs": prefs}


# ── Layer 2: live financial snapshot — tools run FRESH, never remembered ────
def _live_snapshot(conn, user_id: str, tools) -> dict:
    """Re-run the deterministic tools so the agent reasons over TODAY's numbers.

    tools.compute_split / compute_goal_feasibility are the pure functions from
    CLAUDE.md's tool list. They read the ledger and return current state.
    """
    txns = _recent_transactions(conn, user_id, days=90)
    if not txns:
        return {"split": None, "feasibility": None}

    try:
        split = tools.compute_split(txns)
    except ValueError:
        split = None

    goal_row = conn.execute(
        "SELECT id, user_id, goal_type, amount, target_date, engagement, framework, active "
        "FROM goals WHERE user_id=? AND active=1 ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    feasibility = None
    if goal_row and goal_row[2] == "target" and split:
        from datetime import date
        goal = StructuredGoal(
            id=goal_row[0], user_id=goal_row[1], goal_type=goal_row[2],
            amount=goal_row[3],
            target_date=date.fromisoformat(goal_row[4]) if goal_row[4] else None,
            engagement=goal_row[5], framework=goal_row[6], active=bool(goal_row[7]),
        )
        income = split.income_chf
        current_savings = _fetch_savings(conn, user_id)
        try:
            feasibility = tools.compute_goal_feasibility(goal, income or 1.0, current_savings)
        except ValueError:
            pass

    return {"split": split, "feasibility": feasibility}


# ── Layer 3: dialogue — verbatim recent + compressed summary ────────────────
def _load_summary(conn, user_id: str) -> str | None:
    row = conn.execute(
        "SELECT summary FROM conversation_summary WHERE user_id=?",
        (user_id,),
    ).fetchone()
    return row[0] if row else None


def _recent_turns(conn, conversation_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? "
        "ORDER BY ts DESC LIMIT ?",
        (conversation_id, RECENT_TURNS),
    ).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


def _recent_transactions(conn, user_id: str, days: int) -> list[Transaction]:
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


def _fetch_savings(conn, user_id: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(ABS(t.amount)), 0.0) "
        "FROM transactions t JOIN accounts a ON t.account_id=a.id "
        "WHERE a.user_id=? AND t.category='savings'",
        (user_id,),
    ).fetchone()
    return row[0] if row else 0.0


# ── System prompt: structured facts + fresh numbers, NOT remembered ones ────
def _build_system_prompt(persona, profile, snapshot, summary) -> str:
    tone = {
        "neutral": "You are a precise, calm personal finance assistant.",
        "coach": "You are an encouraging personal finance coach.",
    }.get(persona, "You are a personal finance assistant.")

    goal = profile["goal"]
    split = snapshot["split"]

    parts = [
        tone,
        "Currency is CHF. Never do arithmetic yourself — call tools.",
        f"User goal: {_fmt_goal(goal)}",
    ]
    if split is not None:
        from dataclasses import asdict
        parts.append(f"Current 90-day split: {json.dumps(asdict(split))}")
    else:
        parts.append("Current 90-day split: no transaction data yet.")
    if snapshot["feasibility"]:
        from dataclasses import asdict
        parts.append(f"Goal status: {json.dumps(asdict(snapshot['feasibility']))}")
    if summary:
        parts.append(f"Conversation so far (summary): {summary}")
    return "\n".join(parts)


def _fmt_goal(goal) -> str:
    if not goal:
        return "none set yet (onboarding)"
    gtype, amount, date, engagement, framework = goal
    if gtype == "open":
        return f"open-ended saving (engagement={engagement}, framework={framework})"
    return (f"target {amount} CHF by {date} "
            f"(engagement={engagement}, framework={framework})")

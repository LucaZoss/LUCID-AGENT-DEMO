"""
Two-case demo: verify the agent never names a budgeting methodology.

Architecture: tools run locally in Python; the LLM only generates the
user-facing explanation. This means any model works — no tool-calling
protocol required.

Case A — open-ended saver, wants minimal effort  → internal: pay_first
Case B — CHF 10 000 target by December, motivated → internal: zero_based

Run:
    python demo_framework_language.py
    python demo_framework_language.py ollama/mistral:7b-instruct
"""

from __future__ import annotations

import sys
import json
from dataclasses import asdict
from datetime import datetime, date, timedelta

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from db.db_schema import init_db
from llm.config import build_adapter
from skills.skill_loader import read_skill
import tools as tools_module
from contracts import Transaction

console = Console(width=90)

# Framework names the model must NEVER say to users
_BANNED = [
    "pay-yourself-first", "pay yourself first",
    "50/30/20", "fifty-thirty-twenty", "50-30-20",
    "zero-based", "zero based", "ynab",
    "methodology",
]

_ACCENT      = "#38bdf8"
_ACCENT_DEEP = "#1d4ed8"
_DIM         = "#64748b"


# ── Seed data ──────────────────────────────────────────────────────────────────

_SEED_TRANSACTIONS: list[tuple[str, float, str | None]] = [
    ("Salary ACME AG",       5200.00,  None),
    ("Salary ACME AG",       5200.00,  None),
    ("Salary ACME AG",       5200.00,  None),
    ("Miete Zurich",        -1800.00, "need"),
    ("Helsana",              -420.00, "need"),
    ("Coop",                 -480.00, "need"),
    ("Migros",               -220.00, "need"),
    ("SBB Halbtax",          -180.00, "need"),
    ("Swisscom",              -79.00, "need"),
    ("EWZ Strom",             -62.00, "need"),
    ("Netflix",               -13.00, "want"),
    ("Spotify",               -10.00, "want"),
    ("Starbucks",             -42.00, "want"),
    ("Restaurant Helvetia",   -68.00, "want"),
    ("Zara",                  -89.00, "want"),
    ("Kino Kosmos",           -30.00, "want"),
    ("Tibits",                -25.00, "want"),
    ("Amazon.de",             -55.00, "want"),
    ("VIAC 3a",              -400.00, "savings"),
    ("Swissquote",           -200.00, "savings"),
]


def _build_transactions() -> list[Transaction]:
    now = datetime.now()
    txns = []
    for i, (merchant, amount, category) in enumerate(_SEED_TRANSACTIONS):
        days_ago = (i * 3) % 70 + 5
        txns.append(Transaction(
            id=f"seed-{i}",
            account_id="acct-1",
            amount=amount,
            currency="CHF",
            merchant=merchant,
            category=category,
            ts=now - timedelta(days=days_ago),
        ))
    return txns


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_prompt(
    skill_md: str,
    split_json: str,
    goal_context: str,
    user_message: str,
) -> tuple[str, list[dict]]:
    """Build (system_prompt, messages) for a plain text-generation call.

    Tools have already been executed locally; their output is embedded in
    the system prompt so no tool-calling round-trip is needed.
    """
    system = (
        f"{skill_md}\n\n"
        "---\n"
        "TOOLS ALREADY EXECUTED — use these numbers, do not re-compute:\n\n"
        f"compute_current_split (90-day window):\n{split_json}\n\n"
        f"User context:\n{goal_context}\n\n"
        "Currency is CHF. Reply directly to the user — no preamble, no JSON output."
    )
    messages = [{"role": "user", "content": user_message}]
    return system, messages


# ── Case runner ─────────────────────────────────────────────────────────────────

def run_case(
    label: str,
    user_message: str,
    goal_context: str,
    split_json: str,
    skill_md: str,
    llm,
) -> None:
    console.print(Rule(f"[bold]{label}[/bold]", style=f"dim {_ACCENT}"))
    console.print(
        Panel(user_message, title=f"[{_DIM}]user[/{_DIM}]",
              border_style=f"dim #334155", padding=(0, 1))
    )

    system, messages = _build_prompt(skill_md, split_json, goal_context, user_message)

    with console.status(f"[{_DIM}]thinking…[/{_DIM}]",
                        spinner="dots", spinner_style=_ACCENT):
        resp = llm.complete(system=system, messages=messages)

    response = resp.content or "(no response)"
    console.print(
        Panel(response,
              title=f"[bold {_ACCENT}]lucid[/bold {_ACCENT}]",
              border_style=_ACCENT_DEEP, padding=(0, 1))
    )

    lower = response.lower()
    found = [term for term in _BANNED if term in lower]
    if found:
        console.print(f"[bold red]⚠  methodology name leaked:[/bold red] {found}")
    else:
        console.print(f"[{_DIM}]✓  no internal methodology names in response[/{_DIM}]")

    console.print()


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> None:
    model_override = sys.argv[1] if len(sys.argv) > 1 else None
    llm = build_adapter(model_override)
    console.print(f"\n[{_DIM}]model: {llm.model}[/{_DIM}]\n")

    skill_md = read_skill("recommend_framework")

    txns = _build_transactions()
    split = tools_module.compute_split(txns)
    split_json = json.dumps(asdict(split), indent=2)

    # ── Case A: open-ended goal, low engagement ────────────────────────────────
    run_case(
        label="Case A — open-ended saver, minimal effort",
        user_message=(
            "I want to start putting more money aside but I really don't want "
            "to track every purchase or think about categories. Can you suggest "
            "something that'll actually work for me given what I'm already spending?"
        ),
        goal_context=(
            "Goal: open-ended ('save more'). "
            "Engagement: low — user does not want to track categories. "
            "Monthly income: CHF 5,200."
        ),
        split_json=split_json,
        skill_md=skill_md,
        llm=llm,
    )

    # ── Case B: specific target, high engagement ───────────────────────────────
    from tools.feasibility import compute_goal_feasibility
    from contracts import StructuredGoal
    goal = StructuredGoal(
        id="g1", user_id="u1", goal_type="target",
        amount=10_000.0, target_date=date(2026, 12, 31),
        engagement="high",
    )
    feasibility = compute_goal_feasibility(goal, split.income_chf / 3, 0.0)

    run_case(
        label="Case B — CHF 10 000 by December, motivated",
        user_message=(
            "I'm saving for CHF 10,000 by the end of December — it's for a trip "
            "I've already booked. I'm willing to be disciplined and track things "
            "carefully. What's the best plan for me based on my actual spending?"
        ),
        goal_context=(
            f"Goal: CHF 10,000 by 2026-12-31. "
            f"Engagement: high — user is happy to track categories. "
            f"Monthly income: CHF {split.income_chf / 3:,.0f}. "
            f"Required monthly saving: CHF {feasibility.required_monthly_chf:,.0f}. "
            f"Months remaining: {feasibility.months_remaining:.1f}. "
            f"Currently on track: {feasibility.on_track}."
        ),
        split_json=split_json,
        skill_md=skill_md,
        llm=llm,
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Polished TUI REPL for the LUCID personal finance agent.

Presentation layer only — no business logic lives here.
router.handle_message() returns plain text; this file is solely responsible
for colors, panels, spinners, tables, and every other terminal detail.

The router is client-agnostic: the same core serves this REPL, Telegram,
and a future web UI without modification.

Run:
    python -m orchestrator.repl
    python -m orchestrator.repl gpt-4o      # optional model override

    export ANTHROPIC_API_KEY=sk-ant-...     # required for default Claude model
"""

from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone

from pathlib import Path

import pyfiglet
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from bank import make_db_provider
from bank.db_provider import DBBankingProvider
from contracts import Transaction
from db.db_schema import init_db
from llm.config import build_adapter, reconfigure_adapter
from orchestrator.router import handle_message
from orchestrator.startup import USER_ID as _USER_ID, CONV_ID as _CONV_ID, run_startup

from agents.ledger_categorizer import run_ledger_categorizer
from agents import ledger_tools
from ingest.csv_detect import MappingAmbiguity, ResolvedColumnMapping
from ingest.importer import (
    ImportResult,
    import_csv_files,
    preview_csv_file,
    rollback_import_batch,
)
from ingest import profiles

# Last `/import-preview` result — used by `/import-mapping save`
_PENDING_CSV_PREVIEW: dict | None = None

# ── Color palette ──────────────────────────────────────────────────────────────

_BANNER_GRADIENT = [
    "#67e8f9",  # cyan-300
    "#38bdf8",  # sky-400
    "#0ea5e9",  # sky-500
    "#3b82f6",  # blue-500
    "#2563eb",  # blue-600
]

_ACCENT       = "#38bdf8"   # sky-400  — prompts, panel borders, slash highlights
_ACCENT_DEEP  = "#1d4ed8"   # blue-700 — response panel border
_RULE_COLOR   = "#0e7490"   # teal     — horizontal rules
_DIM_TEXT     = "#64748b"   # slate-500
_DIMMER_TEXT  = "#334155"   # slate-700
_GREEN        = "#22c55e"
_AMBER        = "#f59e0b"
_RED          = "#ef4444"
_NEED_COLOR   = "#f59e0b"   # amber   — needs
_WANT_COLOR   = "#818cf8"   # indigo  — wants
_SAVE_COLOR   = "#22c55e"   # green   — savings
_INCOME_COLOR = "#34d399"   # emerald — income

_CONSOLE = Console()

# ── Banner ─────────────────────────────────────────────────────────────────────

def _render_banner() -> None:
    art = pyfiglet.figlet_format("LUCID AGENT", font="slant")
    art_lines = art.rstrip("\n").split("\n")

    content_lines = [l for l in art_lines if l.strip()]
    n = max(len(content_lines) - 1, 1)

    banner = Text(justify="center")
    color_idx = 0
    for line in art_lines:
        if line.strip():
            ratio = color_idx / n
            idx = round(ratio * (len(_BANNER_GRADIENT) - 1))
            banner.append(line + "\n", style=f"bold {_BANNER_GRADIENT[idx]}")
            color_idx += 1
        else:
            banner.append("\n")

    _CONSOLE.print()
    _CONSOLE.print(banner)
    _CONSOLE.print(Rule(style=f"dim {_RULE_COLOR}"))
    _CONSOLE.print(
        f"[{_DIM_TEXT}]Personal finance assistant · CHF[/{_DIM_TEXT}]",
        justify="center",
    )
    _CONSOLE.print(
        f"[{_DIMMER_TEXT}]type "
        f"[bold {_ACCENT}]/help[/bold {_ACCENT}] for commands · "
        f"[bold {_ACCENT}]/setup[/bold {_ACCENT}] for CSV & persistence · "
        f"[bold {_ACCENT}]/quit[/bold {_ACCENT}] to exit"
        f"[/{_DIMMER_TEXT}]",
        justify="center",
    )
    _CONSOLE.print(Rule(style=f"dim {_RULE_COLOR}"))
    _CONSOLE.print()


# ── /help ──────────────────────────────────────────────────────────────────────

def _render_help() -> None:
    body = Text()
    body.append("Commands\n\n", style="bold")
    commands = [
        ("/help                 ", "show this message"),
        ("/setup                ", "CSV import & persistence checklist"),
        ("/model                ", "configure LLM provider or API key"),
        ("/account              ", "show account balance and last 10 transactions"),
        ("/split                ", "show your live needs / wants / savings ratios"),
        ("/goal                 ", "show your active goal and feasibility"),
        ("/txn-add              ", "add a transaction interactively"),
        ("/txn-remove <id>      ", "remove a transaction (with confirmation)"),
        ("/txn-edit <id>        ", "edit a transaction's fields"),
        ("/import <file.csv>    ", "preview + confirm + import a single CSV file (guided)"),
        ("/import               ", "batch-import all *.csv in LUCID_IMPORT_DIR"),
        ("/import preview <f>   ", "dry-run preview only — no rows written"),
        ("/import-rollback <id> ", "remove transactions from an import batch"),
        ("/import-mapping …     ", "list | save <name> | set-default <profile_id>"),
        ("/review-categories    ", "show pending bucket/line proposals + deterministic hint"),
        ("/cat-run              ", "run ledger categorizer LLM on uncategorized outflows"),
        ("/cat-accept <id> …    ", "accept proposal; optional: bucket need line groceries"),
        ("/cat-reject <id>      ", "reject a pending proposal"),
        ("/clear                ", "clear the screen (session continues)"),
        ("/quit                 ", "exit"),
    ]
    for cmd, desc in commands:
        body.append(f"  {cmd}", style=f"bold {_ACCENT}")
        body.append(desc + "\n", style="")

    _CONSOLE.print(Panel(
        body,
        title=f"[bold {_ACCENT}]help[/bold {_ACCENT}]",
        border_style=f"dim {_ACCENT_DEEP}",
        padding=(0, 1),
    ))


# ── /model ─────────────────────────────────────────────────────────────────────

def _cmd_model(current_llm):
    """Let the user pick a new provider; return the new adapter."""
    _CONSOLE.print(
        f"\n[{_DIM_TEXT}]Current model: [bold]{current_llm.model}[/bold][/{_DIM_TEXT}]"
    )
    try:
        new_llm = reconfigure_adapter(console=_CONSOLE)
        _CONSOLE.print(
            Panel(
                f"[bold {_GREEN}]Provider set:[/bold {_GREEN}] {new_llm.model}",
                border_style=f"dim {_ACCENT_DEEP}",
                padding=(0, 1),
            )
        )
        return new_llm
    except (KeyboardInterrupt, SystemExit):
        _CONSOLE.print(f"[{_DIM_TEXT}]Cancelled — keeping {current_llm.model}[/{_DIM_TEXT}]")
        return current_llm


# ── /account ───────────────────────────────────────────────────────────────────

def _cmd_account(bank: DBBankingProvider) -> None:
    """Display accounts and the last 10 transactions via the BankingProvider interface."""
    accounts = bank.get_accounts()
    if not accounts:
        _CONSOLE.print(f"[{_DIM_TEXT}]No accounts found.[/{_DIM_TEXT}]")
        return

    for acc in accounts:
        balance_color = _GREEN if acc.balance >= 0 else _RED
        header = Text()
        header.append(acc.name, style="bold")
        header.append(f"   {acc.currency} ", style=f"dim {_DIM_TEXT}")
        header.append(f"{acc.balance:,.2f}", style=f"bold {balance_color}")

        txns = bank.get_transactions(acc.id, days=90)[:10]

        if not txns:
            _CONSOLE.print(Panel(
                Text.assemble(header, "\n\n", (f"No recent transactions.", _DIM_TEXT)),
                title=f"[bold {_ACCENT}]account[/bold {_ACCENT}]",
                border_style=f"dim {_ACCENT_DEEP}",
                padding=(0, 1),
            ))
            continue

        tbl = Table(
            box=None,
            show_header=True,
            header_style=f"bold {_DIM_TEXT}",
            padding=(0, 1),
        )
        tbl.add_column("Date",     style=f"{_DIMMER_TEXT}", width=12)
        tbl.add_column("Merchant", style="", min_width=26)
        tbl.add_column("Category", width=9)
        tbl.add_column("Amount (CHF)", justify="right", width=14)

        for t in txns:
            cat = t.category or "—"
            cat_color = {
                "need": _NEED_COLOR,
                "want": _WANT_COLOR,
                "savings": _SAVE_COLOR,
            }.get(cat, _DIM_TEXT)

            amt_color = _INCOME_COLOR if t.amount >= 0 else (
                _RED if abs(t.amount) > 500 else ""
            )
            sign = "+" if t.amount >= 0 else ""

            tbl.add_row(
                t.ts.strftime("%d %b %Y"),
                t.merchant,
                f"[{cat_color}]{cat}[/{cat_color}]",
                f"[{amt_color}]{sign}{t.amount:,.2f}[/{amt_color}]" if amt_color
                else f"{sign}{t.amount:,.2f}",
            )

        inner = Text()
        inner.append_text(header)
        inner.append("\n")

        _CONSOLE.print(Panel(
            inner,
            title=f"[bold {_ACCENT}]account[/bold {_ACCENT}]",
            border_style=f"dim {_ACCENT_DEEP}",
            padding=(0, 1),
        ))
        _CONSOLE.print(tbl)


# ── /split ─────────────────────────────────────────────────────────────────────

def _cmd_split(conn, user_id: str) -> None:
    """Show live needs/wants/savings ratios via compute_split."""
    from tools.split import compute_split
    from orchestrator.router import _fetch_transactions  # type: ignore[attr-defined]

    txns = _fetch_transactions(conn, user_id, 90)
    if not txns:
        _CONSOLE.print(f"[{_DIM_TEXT}]No transactions in the last 90 days.[/{_DIM_TEXT}]")
        return

    try:
        s = compute_split(txns)
    except ValueError as exc:
        _CONSOLE.print(f"[{_RED}]{exc}[/{_RED}]")
        return

    def _bar(pct: float, color: str, width: int = 30) -> Text:
        filled = round(pct / 100 * width)
        bar = Text()
        bar.append("█" * filled, style=f"bold {color}")
        bar.append("░" * (width - filled), style=f"dim {_DIMMER_TEXT}")
        return bar

    body = Text()
    body.append("90-day income\n", style=f"dim {_DIM_TEXT}")
    body.append(f"  CHF {s.income_chf:,.2f}\n\n", style="bold")

    for label, chf, pct, color in [
        ("Needs   ", s.needs_chf,   s.needs_pct,   _NEED_COLOR),
        ("Wants   ", s.wants_chf,   s.wants_pct,   _WANT_COLOR),
        ("Savings ", s.savings_chf, s.savings_pct, _SAVE_COLOR),
    ]:
        body.append(f"  {label}", style=f"bold {color}")
        body.append(f"{pct:5.1f}%  CHF {chf:,.2f}\n", style="")
        body.append("  ")
        body.append_text(_bar(pct, color))
        body.append("\n\n")

    _CONSOLE.print(Panel(
        body,
        title=f"[bold {_ACCENT}]split[/bold {_ACCENT}]",
        border_style=f"dim {_ACCENT_DEEP}",
        padding=(0, 1),
    ))


# ── /goal ──────────────────────────────────────────────────────────────────────

def _cmd_goal(conn, user_id: str) -> None:
    """Show the active goal and feasibility."""
    from tools.feasibility import compute_goal_feasibility
    from tools.split import compute_split
    from orchestrator.router import _fetch_transactions, _fetch_savings_total  # type: ignore[attr-defined]
    from contracts import StructuredGoal
    from datetime import date

    row = conn.execute(
        "SELECT id, user_id, goal_type, amount, target_date, engagement, framework, active "
        "FROM goals WHERE user_id=? AND active=1 ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()

    if not row:
        _CONSOLE.print(Panel(
            f"[{_DIM_TEXT}]No active goal. Chat with the agent to set one.[/{_DIM_TEXT}]",
            title=f"[bold {_ACCENT}]goal[/bold {_ACCENT}]",
            border_style=f"dim {_ACCENT_DEEP}",
            padding=(0, 1),
        ))
        return

    goal = StructuredGoal(
        id=row[0], user_id=row[1], goal_type=row[2], amount=row[3],
        target_date=date.fromisoformat(row[4]) if row[4] else None,
        engagement=row[5], framework=row[6], active=bool(row[7]),
    )

    body = Text()
    body.append("Type         ", style=f"dim {_DIM_TEXT}")
    body.append(goal.goal_type + "\n", style="bold")
    if goal.amount:
        body.append("Target       ", style=f"dim {_DIM_TEXT}")
        body.append(f"CHF {goal.amount:,.0f}\n", style=f"bold {_GREEN}")
    if goal.target_date:
        body.append("By           ", style=f"dim {_DIM_TEXT}")
        body.append(str(goal.target_date) + "\n", style="bold")
    body.append("Engagement   ", style=f"dim {_DIM_TEXT}")
    body.append((goal.engagement or "—") + "\n", style="bold")
    body.append("Framework    ", style=f"dim {_DIM_TEXT}")
    body.append((goal.framework or "not set") + "\n", style="bold")

    if goal.goal_type == "target" and goal.amount and goal.target_date:
        txns = _fetch_transactions(conn, user_id, 90)
        income = 0.0
        if txns:
            try:
                income = compute_split(txns).income_chf
            except ValueError:
                pass
        current_savings = _fetch_savings_total(conn, user_id)
        try:
            f = compute_goal_feasibility(goal, income or 1.0, current_savings)
            body.append("\n")
            body.append("Monthly needed ", style=f"dim {_DIM_TEXT}")
            body.append(f"CHF {f.required_monthly:,.0f}\n", style="bold")
            body.append("On track       ", style=f"dim {_DIM_TEXT}")
            if f.on_track:
                body.append("yes\n", style=f"bold {_GREEN}")
            else:
                body.append("no\n", style=f"bold {_RED}")
        except (ValueError, Exception):
            pass

    _CONSOLE.print(Panel(
        body,
        title=f"[bold {_ACCENT}]goal[/bold {_ACCENT}]",
        border_style=f"dim {_ACCENT_DEEP}",
        padding=(0, 1),
    ))


# ── /fire ──────────────────────────────────────────────────────────────────────

def _cmd_fire(args: list[str], bank: DBBankingProvider, conn) -> None:
    """/fire <amount> <merchant…>  — inject a test transaction."""
    if len(args) < 2:
        _CONSOLE.print(
            f"[{_DIM_TEXT}]Usage: /fire <amount> <merchant>\n"
            f"  e.g.  /fire -120 Digitec Galaxus[/{_DIM_TEXT}]"
        )
        return

    try:
        amount = float(args[0])
    except ValueError:
        _CONSOLE.print(f"[{_RED}]Invalid amount: {args[0]!r}[/{_RED}]")
        return

    merchant = " ".join(args[1:])

    accounts = bank.get_accounts()
    if not accounts:
        _CONSOLE.print(f"[{_RED}]No accounts found.[/{_RED}]")
        return
    account_id = accounts[0].id

    from tools.categorize import categorize_transaction

    txn = Transaction(
        id=f"fire-{uuid.uuid4().hex[:8]}",
        account_id=account_id,
        amount=round(amount, 2),
        currency="CHF",
        merchant=merchant,
        category=None,
        ts=datetime.now(timezone.utc),
    )
    txn.category = categorize_transaction(txn)

    bank.fire_transaction(txn)

    sign = "+" if amount >= 0 else ""
    color = _INCOME_COLOR if amount >= 0 else _RED
    _CONSOLE.print(Panel(
        Text.assemble(
            ("Injected transaction\n\n", f"bold"),
            ("Merchant   ", f"dim {_DIM_TEXT}"), (merchant + "\n", ""),
            ("Amount     ", f"dim {_DIM_TEXT}"), (f"{sign}{amount:,.2f} CHF\n", f"bold {color}"),
            ("Category   ", f"dim {_DIM_TEXT}"), ((txn.category or "—") + "\n", "bold"),
            ("ID         ", f"dim {_DIM_TEXT}"), (txn.id + "\n", f"dim {_DIMMER_TEXT}"),
        ),
        title=f"[bold {_ACCENT}]fire[/bold {_ACCENT}]",
        border_style=f"dim {_ACCENT_DEEP}",
        padding=(0, 1),
    ))


# ── Agent response ─────────────────────────────────────────────────────────────

def _render_response(text: str) -> None:
    md_markers = ("```", "**", "##", "\n- ", "\n* ", "| --", "---\n")
    content = Markdown(text) if any(m in text for m in md_markers) else text

    _CONSOLE.print(Panel(
        content,
        title=f"[bold {_ACCENT}]lucid[/bold {_ACCENT}]",
        border_style=_ACCENT_DEEP,
        padding=(0, 1),
    ))


# ── Demo DB seeding ────────────────────────────────────────────────────────────

def _seed_demo_data(conn) -> None:
    now = datetime.now()
    account_id = "demo-account-1"

    conn.execute(
        "INSERT OR IGNORE INTO users(id, display_name, created_at) VALUES(?,?,?)",
        (_USER_ID, "Demo User", now.isoformat()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO accounts(id, user_id, name, balance, currency) "
        "VALUES(?,?,?,?,?)",
        (account_id, _USER_ID, "Zürcher Kantonalbank Checking", 3200.00, "CHF"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO conversations(id, user_id, started_at) VALUES(?,?,?)",
        (_CONV_ID, _USER_ID, now.isoformat()),
    )
    conn.execute("INSERT OR IGNORE INTO prefs(user_id) VALUES(?)", (_USER_ID,))

    for i, (merchant, amount, category) in enumerate(_DEMO_TRANSACTIONS):
        days_ago = (i * 3) % 75 + 3
        ts = (now - timedelta(days=days_ago)).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO transactions"
            "(id, account_id, amount, currency, merchant, category, ts) "
            "VALUES(?,?,?,?,?,?,?)",
            (f"seed-{i}", account_id, amount, "CHF", merchant, category, ts),
        )
    conn.commit()


def _seed_minimal_user(conn) -> None:
    """User + empty account for CSV import mode (no demo transactions)."""
    now = datetime.now()
    account_id = "demo-account-1"
    conn.execute(
        "INSERT OR IGNORE INTO users(id, display_name, created_at) VALUES(?,?,?)",
        (_USER_ID, "Import User", now.isoformat()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO accounts(id, user_id, name, balance, currency) "
        "VALUES(?,?,?,?,?)",
        (account_id, _USER_ID, "Imported ledger", 0.0, "CHF"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO conversations(id, user_id, started_at) VALUES(?,?,?)",
        (_CONV_ID, _USER_ID, now.isoformat()),
    )
    conn.execute("INSERT OR IGNORE INTO prefs(user_id) VALUES(?)", (_USER_ID,))
    conn.commit()


def _seed_demo_data(conn) -> None:
    """Legacy shim — seeding is now handled by orchestrator.startup._seed_demo.
    Kept only so existing tests that call this directly continue to work."""
    from orchestrator.startup import _seed_demo, ACCOUNT_ID
    _seed_demo(conn, _USER_ID, ACCOUNT_ID, _CONV_ID)


def _seed_minimal_user(conn) -> None:
    """Legacy shim — seeding is now handled by orchestrator.startup._seed_minimal."""
    from orchestrator.startup import _seed_minimal, ACCOUNT_ID
    _seed_minimal(conn, _USER_ID, ACCOUNT_ID, _CONV_ID)


def _import_dir() -> Path:
    """Directory scanned for ``/import`` (override with ``LUCID_IMPORT_DIR``)."""
    p = os.environ.get("LUCID_IMPORT_DIR", "data/imports")
    d = Path(p)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _render_setup_help() -> None:
    """Print a step-by-step checklist for CSV import and a persistent SQLite DB."""
    imp = _import_dir().resolve()
    db_raw = os.environ.get("LUCID_DB_PATH")
    db_disp = db_raw if db_raw else ":memory: (default — data not saved after exit)"
    ledger = os.environ.get("LUCID_LEDGER", "demo")

    body = Text()
    body.append("Getting started with your own CSV data\n\n", style="bold")
    body.append("1. Put bank CSV files in this folder:\n   ", style="")
    body.append(str(imp), style=f"bold {_ACCENT}")
    body.append(
        "\n   Or set LUCID_IMPORT_DIR to another path before starting the REPL.\n\n",
        style=f"dim {_DIM_TEXT}",
    )
    body.append("2. Optional — start with an empty ledger (no demo transactions):\n   ", style="")
    body.append("LUCID_LEDGER=import", style="bold")
    body.append(" then restart the REPL.\n\n", style="")

    body.append("3. Persist imports & mapping profiles across sessions:\n   ", style="")
    body.append("Set LUCID_DB_PATH", style="bold")
    body.append(
        " to a SQLite file, e.g. lucid_demo.db, in the environment before launch.\n"
        "   The REPL reads ",
        style="",
    )
    body.append("os.environ", style="bold")
    body.append(
        " only — a line in .env is not loaded automatically unless your shell or IDE loads it.\n"
        "   PowerShell:  ",
        style=f"dim {_DIM_TEXT}",
    )
    body.append('$env:LUCID_DB_PATH="lucid_demo.db"', style="bold")
    body.append("\n   bash:         ", style=f"dim {_DIM_TEXT}")
    body.append("export LUCID_DB_PATH=./lucid_demo.db\n\n", style="bold")

    body.append("4. In the REPL:\n   ", style="")
    body.append("/import yourfile.csv", style=f"bold {_ACCENT}")
    body.append(
        " — guided flow: shows detected mapping + 3 sample rows,\n"
        "     asks y/N before writing anything. Works for most bank CSV formats.\n   ",
        style="",
    )
    body.append("/import preview yourfile.csv", style=f"bold {_ACCENT}")
    body.append(" — dry-run preview (no import)\n   ", style="")
    body.append("/import-mapping save MyBank", style=f"bold {_ACCENT}")
    body.append(
        " — save the detected column mapping as a profile\n"
        "     (auto-matched on future imports of files with the same headers)\n   ",
        style="",
    )
    body.append("/import", style=f"bold {_ACCENT}")
    body.append(" — batch-import all *.csv from the import folder\n   ", style="")
    body.append("/cat-run", style=f"bold {_ACCENT}")
    body.append(" → ", style="")
    body.append("/review-categories", style=f"bold {_ACCENT}")
    body.append(" → ", style="")
    body.append("/cat-accept …", style=f"bold {_ACCENT}")
    body.append(" for LLM proposals (needs API key).\n\n", style="")

    body.append("Current environment\n", style=f"dim {_DIM_TEXT}")
    body.append(f"  import folder  → {imp}\n", style="")
    body.append(f"  LUCID_DB_PATH   → {db_disp}\n", style="")
    body.append(f"  LUCID_LEDGER    → {ledger}\n", style="")

    _CONSOLE.print(Panel(
        body,
        title=f"[bold {_ACCENT}]setup[/bold {_ACCENT}]",
        border_style=f"dim {_ACCENT_DEEP}",
        padding=(0, 1),
    ))


def _is_first_run(conn, user_id: str) -> bool:
    """Return True if the user has no active goal (= has not completed onboarding)."""
    row = conn.execute(
        "SELECT 1 FROM goals WHERE user_id=? AND active=1 LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is None


def _run_onboarding(llm, conn, bank: DBBankingProvider) -> None:
    """Kick off the goal_intake skill and hand control to the user."""
    _CONSOLE.print(Panel(
        Text.assemble(
            ("Welcome to Lucid Agent!\n\n", f"bold {_ACCENT}"),
            (
                "It looks like this is your first time here.\n"
                "I'll help you define a financial goal and build a budget\n"
                "that actually fits your life in Switzerland.\n\n",
                "",
            ),
            ("Let's get started.", f"dim {_DIM_TEXT}"),
        ),
        title=f"[bold {_ACCENT}]onboarding[/bold {_ACCENT}]",
        border_style=f"dim {_ACCENT_DEEP}",
        padding=(1, 2),
    ))

    # Kick the agent — the goal_intake skill takes it from here
    _CONSOLE.print()
    with _CONSOLE.status(
        f"[{_DIM_TEXT}]thinking…[/{_DIM_TEXT}]",
        spinner="dots",
        spinner_style=_ACCENT,
    ):
        response = handle_message(
            llm=llm,
            conn=conn,
            user_id=_USER_ID,
            conversation_id=_CONV_ID,
            user_message=(
                "Hi, I'm a new user and I'd like to set a financial goal "
                "and get started with budgeting."
            ),
        )
    _render_response(response)


# ── CSV import & ledger categorization (REPL glue) ─────────────────────────────


def _resolve_csv_path(name: str) -> Path | None:
    """Find a CSV by name in LUCID_IMPORT_DIR or as an absolute path."""
    p = Path(name)
    if p.is_absolute() and p.is_file():
        return p
    candidate = _import_dir() / name
    if candidate.is_file():
        return candidate
    return None


def _render_preview_panel(prev: dict) -> None:
    """Print detection summary + sample rows table for a preview result."""
    global _PENDING_CSV_PREVIEW
    det = prev["detection"]

    msg = (
        f"path: {prev['path']}\n"
        f"encoding: {prev['encoding']}  delimiter: {prev['delimiter']!r}\n"
        f"header_hash: {prev['header_hash']}\n"
    )
    if isinstance(det, MappingAmbiguity):
        msg += f"\n[{_RED}]mapping failed — {det.message}[/{_RED}]\n"
        msg += f"[{_DIM_TEXT}]headers found: {', '.join(prev['headers'])}[/{_DIM_TEXT}]\n"
        if det.best_effort:
            msg += f"[{_AMBER}]best-effort: {', '.join(f'{k}→{v}' for k,v in det.best_effort.items())}[/{_AMBER}]\n"
        msg += (
            f"\n[{_DIM_TEXT}]Tip: run [bold]/import-mapping save MyBank[/bold] after the "
            f"preview succeeds, or override mapping manually.[/{_DIM_TEXT}]"
        )
    else:
        msg += f"\n[{_GREEN}]mapping OK[/{_GREEN}]  sign_rule={det.sign_rule}\n"
        msg += "columns: " + ", ".join(f"[bold]{k}[/bold]→{v}" for k, v in det.column_map.items())

    _CONSOLE.print(Panel(msg, title="import preview", border_style=_ACCENT_DEEP))

    if prev["sample_rows"]:
        tbl = Table(title="sample rows (first 5)", box=None, show_lines=True)
        keys = list(prev["sample_rows"][0].keys())
        for k in keys:
            tbl.add_column(k[:18], overflow="fold", max_width=22)
        for row in prev["sample_rows"]:
            tbl.add_row(*(str(row.get(k, ""))[:60] for k in keys))
        _CONSOLE.print(tbl)


def _print_import_result(r: ImportResult) -> None:
    color = _RED if r.skipped else _GREEN
    body = f"[bold]{Path(r.path).name}[/bold]  [{color}]{r.message}[/{color}]\n"
    if r.batch_id:
        body += (
            f"  batch  {r.batch_id[:8]}…\n"
            f"  inserted [{_GREEN}]{r.rows_inserted}[/{_GREEN}]  "
            f"duplicates skipped {r.rows_skipped_duplicate}  "
            f"invalid {r.rows_skipped_invalid}\n"
        )
    for w in r.warnings:
        body += f"  [{_AMBER}]⚠  {w}[/{_AMBER}]\n"
    _CONSOLE.print(Panel(body.rstrip(), title="import", border_style=_ACCENT_DEEP))


def _cmd_import_run(conn: sqlite3.Connection, bank: DBBankingProvider, parts: list[str]) -> None:
    """Guided single-file import OR batch import of all *.csv in LUCID_IMPORT_DIR."""
    global _PENDING_CSV_PREVIEW
    force = any(p in ("--force", "force") for p in parts)

    accounts = bank.get_accounts()
    if not accounts:
        _CONSOLE.print(f"[{_RED}]No account to import into.[/{_RED}]")
        return
    acc_id = accounts[0].id

    # Find optional profile override.
    profile_id: str | None = None
    for i, p in enumerate(parts):
        if p == "profile" and i + 1 < len(parts):
            profile_id = parts[i + 1]
            break

    # Single-file guided mode: /import <filename.csv>
    filename_arg = next(
        (p for p in parts[1:] if p.endswith(".csv") and p != "profile"), None
    )
    if filename_arg:
        path = _resolve_csv_path(filename_arg)
        if path is None:
            _CONSOLE.print(
                f"[{_RED}]File not found: {filename_arg}[/{_RED}]\n"
                f"[{_DIM_TEXT}]Import dir: {_import_dir().resolve()}[/{_DIM_TEXT}]"
            )
            return

        prev = preview_csv_file(path)
        _PENDING_CSV_PREVIEW = {"path": str(path), "preview": prev}
        _render_preview_panel(prev)

        det = prev["detection"]
        if isinstance(det, MappingAmbiguity):
            _CONSOLE.print(
                f"[{_RED}]Cannot import — column mapping is ambiguous (see above).[/{_RED}]\n"
                f"[{_DIM_TEXT}]Fix the CSV headers or save a custom mapping profile.[/{_DIM_TEXT}]"
            )
            return

        try:
            answer = _CONSOLE.input(
                f"\n[{_ACCENT}]Import {path.name} into your ledger? [[bold]y[/bold]/N] [/{_ACCENT}]"
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            _CONSOLE.print(f"[{_DIM_TEXT}]Import cancelled.[/{_DIM_TEXT}]")
            return

        if answer != "y":
            _CONSOLE.print(f"[{_DIM_TEXT}]Import cancelled.[/{_DIM_TEXT}]")
            return

        results = import_csv_files(
            conn, _USER_ID, acc_id, [path],
            profile_id=profile_id, force_reimport=force,
        )
        for r in results:
            _print_import_result(r)
        return

    # Batch mode: /import (no filename)
    d = _import_dir()
    csvs = sorted(d.glob("*.csv"))
    if not csvs:
        _CONSOLE.print(
            f"[{_DIM_TEXT}]No CSV files in {d.resolve()}.\n"
            f"Drop exports there, set LUCID_IMPORT_DIR, "
            f"or use [bold]/import <filename.csv>[/bold] with a path.[/{_DIM_TEXT}]"
        )
        return

    _CONSOLE.print(
        f"[{_DIM_TEXT}]Found {len(csvs)} file(s) in {d.resolve()} — importing…[/{_DIM_TEXT}]"
    )
    results = import_csv_files(
        conn, _USER_ID, acc_id, csvs, profile_id=profile_id, force_reimport=force,
    )
    for r in results:
        _print_import_result(r)


def _cmd_import_preview(parts: list[str]) -> None:
    """Dry-run preview: show header detection + sample rows, no import."""
    global _PENDING_CSV_PREVIEW
    # Support both '/import preview <f>' and '/import-preview <f>'
    name = parts[2] if len(parts) >= 3 else (parts[1] if len(parts) >= 2 else "")
    if not name or not name.endswith(".csv"):
        _CONSOLE.print(
            f"[{_DIM_TEXT}]Usage: /import preview <filename.csv>[/{_DIM_TEXT}]"
        )
        return
    path = _resolve_csv_path(name)
    if path is None:
        _CONSOLE.print(
            f"[{_RED}]File not found: {name}[/{_RED}]\n"
            f"[{_DIM_TEXT}]Import dir: {_import_dir().resolve()}[/{_DIM_TEXT}]"
        )
        return
    prev = preview_csv_file(path)
    _PENDING_CSV_PREVIEW = {"path": str(path), "preview": prev}
    _render_preview_panel(prev)


def _cmd_import_rollback(conn: sqlite3.Connection, bank: DBBankingProvider, parts: list[str]) -> None:
    if len(parts) < 2:
        _CONSOLE.print(f"[{_DIM_TEXT}]Usage: /import-rollback <batch_id>[/{_DIM_TEXT}]")
        return
    bid = parts[1]
    acc = bank.get_accounts()[0].id
    ok, msg = rollback_import_batch(conn, _USER_ID, acc, bid)
    color = _GREEN if ok else _RED
    _CONSOLE.print(f"[{color}]{msg}[/{color}]")


def _cmd_import_mapping(conn: sqlite3.Connection, parts: list[str]) -> None:
    global _PENDING_CSV_PREVIEW
    sub = (parts[1] if len(parts) > 1 else "list").lower()
    if sub == "list":
        rows = profiles.list_profiles(conn, _USER_ID)
        if not rows:
            _CONSOLE.print(f"[{_DIM_TEXT}]No saved mapping profiles.[/{_DIM_TEXT}]")
            return
        t = Table(box=None)
        t.add_column("id")
        t.add_column("name")
        t.add_column("default")
        for r in rows:
            t.add_row(r["id"][:8] + "…", r["display_name"], "yes" if r["is_default"] else "")
        _CONSOLE.print(Panel(t, title="mapping profiles", border_style=_ACCENT_DEEP))
    elif sub == "save" and len(parts) >= 3:
        if not _PENDING_CSV_PREVIEW:
            _CONSOLE.print(
                f"[{_RED}]Run /import-preview <file> first to capture a mapping.[/{_RED}]"
            )
            return
        pr = _PENDING_CSV_PREVIEW["preview"]
        det = pr["detection"]
        if isinstance(det, MappingAmbiguity):
            _CONSOLE.print(f"[{_RED}]Last preview has ambiguous mapping — fix CSV or columns.[/{_RED}]")
            return
        assert isinstance(det, ResolvedColumnMapping)
        name = " ".join(parts[2:])
        pid = profiles.save_profile(
            conn,
            _USER_ID,
            name,
            det.column_map,
            sign_rule=det.sign_rule,
            encoding=det.encoding,
            delimiter=det.delimiter,
            headers=pr["headers"],
        )
        _CONSOLE.print(f"[{_GREEN}]Saved profile {pid} as {name!r}[/{_GREEN}]")
    elif sub == "set-default" and len(parts) >= 3:
        profiles.set_default_profile(conn, _USER_ID, parts[2])
        _CONSOLE.print(f"[{_GREEN}]Default profile updated.[/{_GREEN}]")
    else:
        _CONSOLE.print(
            f"[{_DIM_TEXT}]Usage: /import-mapping list | save <name> | "
            f"set-default <profile_id>[/{_DIM_TEXT}]"
        )


def _cmd_review_categories(conn: sqlite3.Connection) -> None:
    from tools.categorize import categorize_transaction

    pending = ledger_tools.list_pending_proposals(conn, _USER_ID, 40)
    if not pending:
        _CONSOLE.print(f"[{_DIM_TEXT}]No pending category proposals.[/{_DIM_TEXT}]")
        return
    t = Table(box=None, show_lines=True)
    t.add_column("proposal_id", max_width=14, overflow="fold")
    t.add_column("txn_id", max_width=14, overflow="fold")
    t.add_column("merchant", max_width=24, overflow="fold")
    t.add_column("amt")
    t.add_column("bucket")
    t.add_column("line")
    t.add_column("det.need")
    for p in pending:
        dummy = Transaction(
            id=p["txn_id"],
            account_id="x",
            amount=float(p["amount"]),
            currency="CHF",
            merchant=p["merchant"],
            category=None,
            ts=datetime.now(timezone.utc),
        )
        det = categorize_transaction(dummy)
        t.add_row(
            p["proposal_id"][:12] + "…",
            p["txn_id"][:12] + "…",
            p["merchant"],
            f"{p['amount']:.2f}",
            p["proposed_bucket"] or "—",
            p["proposed_line"] or "—",
            det,
        )
    _CONSOLE.print(
        Panel(
            t,
            title="pending proposals (/cat-accept <id> [bucket] [line] | /cat-reject <id>)",
            border_style=_ACCENT_DEEP,
        )
    )


def _cmd_cat_accept(conn: sqlite3.Connection, parts: list[str]) -> None:
    if len(parts) < 2:
        _CONSOLE.print(
            f"[{_DIM_TEXT}]Usage: /cat-accept <proposal_id> [bucket need] [line groceries][/{_DIM_TEXT}]"
        )
        return
    pid = parts[1]
    bucket_o: str | None = None
    line_o: str | None = None
    # optional: /cat-accept pid bucket need line groceries
    if "bucket" in parts:
        i = parts.index("bucket")
        if i + 1 < len(parts):
            bucket_o = parts[i + 1]
    if "line" in parts:
        i = parts.index("line")
        if i + 1 < len(parts):
            line_o = parts[i + 1]
    res = ledger_tools.apply_proposal(
        conn, _USER_ID, pid, bucket_override=bucket_o, line_override=line_o,
    )
    if res.get("ok"):
        _CONSOLE.print(f"[{_GREEN}]Applied: {res}[/{_GREEN}]")
    else:
        _CONSOLE.print(f"[{_RED}]{res}[/{_RED}]")


def _cmd_cat_reject(conn: sqlite3.Connection, parts: list[str]) -> None:
    if len(parts) < 2:
        _CONSOLE.print(f"[{_DIM_TEXT}]Usage: /cat-reject <proposal_id>[/{_DIM_TEXT}]")
        return
    ok = ledger_tools.reject_proposal(conn, _USER_ID, parts[1])
    _CONSOLE.print(
        f"[{_GREEN if ok else _RED}]rejected={ok}[/{_GREEN if ok else _RED}]"
    )


def _cmd_cat_run(conn: sqlite3.Connection, llm) -> None:
    with _CONSOLE.status("ledger categorizer…", spinner="dots", spinner_style=_ACCENT):
        out = run_ledger_categorizer(llm, conn, _USER_ID)
    _CONSOLE.print(Panel(out, title="ledger categorizer", border_style=_ACCENT_DEEP))


# ── Transaction editing ────────────────────────────────────────────────────────

def _cmd_txn_add(bank: DBBankingProvider, conn: sqlite3.Connection) -> None:
    """/txn-add — interactively add a transaction."""
    from tools.categorize import categorize_transaction

    try:
        merchant = _CONSOLE.input(f"[{_ACCENT}]Merchant: [/{_ACCENT}]").strip()
        if not merchant:
            return
        amt_str = _CONSOLE.input(
            f"[{_ACCENT}]Amount in CHF (negative = outflow): [/{_ACCENT}]"
        ).strip()
        amount = float(amt_str)
        date_str = _CONSOLE.input(
            f"[{_ACCENT}]Date YYYY-MM-DD (blank = today): [/{_ACCENT}]"
        ).strip()
        ts = (
            datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            if date_str
            else datetime.now(timezone.utc)
        )
        cat_str = _CONSOLE.input(
            f"[{_ACCENT}]Category (need/want/savings, blank = auto): [/{_ACCENT}]"
        ).strip().lower() or None
    except (EOFError, KeyboardInterrupt):
        _CONSOLE.print(f"[{_DIM_TEXT}]Cancelled.[/{_DIM_TEXT}]")
        return
    except ValueError as exc:
        _CONSOLE.print(f"[{_RED}]{exc}[/{_RED}]")
        return

    accounts = bank.get_accounts()
    if not accounts:
        _CONSOLE.print(f"[{_RED}]No account found.[/{_RED}]")
        return

    dummy = Transaction(
        id="x", account_id=accounts[0].id, amount=amount,
        currency="CHF", merchant=merchant, category=None, ts=ts,
    )
    txn = Transaction(
        id=f"txn-{uuid.uuid4().hex[:8]}",
        account_id=accounts[0].id,
        amount=round(amount, 2),
        currency="CHF",
        merchant=merchant,
        category=cat_str if cat_str in ("need", "want", "savings") else categorize_transaction(dummy),
        ts=ts,
    )
    bank.fire_transaction(txn)

    sign = "+" if amount >= 0 else ""
    color = _INCOME_COLOR if amount >= 0 else _RED
    _CONSOLE.print(Panel(
        Text.assemble(
            ("Transaction added\n\n", "bold"),
            ("Merchant  ", f"dim {_DIM_TEXT}"), (merchant + "\n", ""),
            ("Amount    ", f"dim {_DIM_TEXT}"),
            (f"{sign}{amount:,.2f} CHF\n", f"bold {color}"),
            ("Category  ", f"dim {_DIM_TEXT}"), ((txn.category or "—") + "\n", "bold"),
            ("ID        ", f"dim {_DIM_TEXT}"), (txn.id + "\n", f"dim {_DIMMER_TEXT}"),
        ),
        title=f"[bold {_ACCENT}]txn-add[/bold {_ACCENT}]",
        border_style=f"dim {_ACCENT_DEEP}",
        padding=(0, 1),
    ))


def _cmd_txn_remove(
    conn: sqlite3.Connection, bank: DBBankingProvider, parts: list[str]
) -> None:
    """/txn-remove <id> — remove a transaction with confirmation."""
    if len(parts) < 2:
        _CONSOLE.print(f"[{_DIM_TEXT}]Usage: /txn-remove <transaction_id>[/{_DIM_TEXT}]")
        return

    txn_id = parts[1]
    row = conn.execute(
        "SELECT t.merchant, t.amount, t.account_id FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id WHERE t.id=? AND a.user_id=?",
        (txn_id, _USER_ID),
    ).fetchone()
    if not row:
        _CONSOLE.print(f"[{_RED}]Transaction not found: {txn_id}[/{_RED}]")
        return

    merchant, amount, account_id = row
    try:
        confirm = _CONSOLE.input(
            f"[{_ACCENT}]Remove [{merchant}  CHF {amount:,.2f}]? [y/N] [/{_ACCENT}]"
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        _CONSOLE.print(f"[{_DIM_TEXT}]Cancelled.[/{_DIM_TEXT}]")
        return

    if confirm != "y":
        _CONSOLE.print(f"[{_DIM_TEXT}]Cancelled.[/{_DIM_TEXT}]")
        return

    conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    conn.execute(
        "UPDATE accounts SET balance = "
        "(SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id=?) "
        "WHERE id=?",
        (account_id, account_id),
    )
    conn.commit()
    _CONSOLE.print(f"[{_GREEN}]Transaction {txn_id} removed.[/{_GREEN}]")


def _cmd_txn_edit(
    conn: sqlite3.Connection, bank: DBBankingProvider, parts: list[str]
) -> None:
    """/txn-edit <id> — edit a transaction's fields interactively."""
    if len(parts) < 2:
        _CONSOLE.print(f"[{_DIM_TEXT}]Usage: /txn-edit <transaction_id>[/{_DIM_TEXT}]")
        return

    txn_id = parts[1]
    row = conn.execute(
        "SELECT t.merchant, t.amount, t.category, t.ts, t.account_id FROM transactions t "
        "JOIN accounts a ON t.account_id=a.id WHERE t.id=? AND a.user_id=?",
        (txn_id, _USER_ID),
    ).fetchone()
    if not row:
        _CONSOLE.print(f"[{_RED}]Transaction not found: {txn_id}[/{_RED}]")
        return

    merchant, amount, category, ts, account_id = row
    _CONSOLE.print(
        f"[{_DIM_TEXT}]Editing {txn_id}  "
        f"[{merchant}  CHF {amount:,.2f}  {category or '—'}  {ts}]\n"
        f"Press Enter to keep the current value.[/{_DIM_TEXT}]"
    )

    try:
        new_merchant = (
            _CONSOLE.input(f"[{_ACCENT}]Merchant [{merchant}]: [/{_ACCENT}]").strip()
            or merchant
        )
        amt_str = _CONSOLE.input(
            f"[{_ACCENT}]Amount [{amount:,.2f}]: [/{_ACCENT}]"
        ).strip()
        new_amount = float(amt_str) if amt_str else amount
        cat_input = _CONSOLE.input(
            f"[{_ACCENT}]Category [{category or '—'}] (need/want/savings): [/{_ACCENT}]"
        ).strip().lower()
        new_cat = cat_input if cat_input in ("need", "want", "savings") else category
    except (EOFError, KeyboardInterrupt):
        _CONSOLE.print(f"[{_DIM_TEXT}]Cancelled.[/{_DIM_TEXT}]")
        return
    except ValueError as exc:
        _CONSOLE.print(f"[{_RED}]{exc}[/{_RED}]")
        return

    conn.execute(
        "UPDATE transactions SET merchant=?, amount=?, category=? WHERE id=?",
        (new_merchant, round(new_amount, 2), new_cat, txn_id),
    )
    conn.execute(
        "UPDATE accounts SET balance = "
        "(SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id=?) "
        "WHERE id=?",
        (account_id, account_id),
    )
    conn.commit()
    _CONSOLE.print(f"[{_GREEN}]Transaction {txn_id} updated.[/{_GREEN}]")


# ── REPL loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    model_override = sys.argv[1] if len(sys.argv) > 1 else None

    _render_banner()

    # Run staged startup: model → data source → (persistence → import → categorize → summary)
    state = run_startup(_CONSOLE, model_override)
    llm = state.llm
    conn = state.conn
    bank: DBBankingProvider = state.bank  # type: ignore[assignment]

    # DEMO path: run onboarding on first run, greet returning user otherwise
    if state.data_source == "demo":
        if state.is_first_run:
            _run_onboarding(llm, conn, bank)
        else:
            _CONSOLE.print(
                Panel(
                    f"[{_DIM_TEXT}]Welcome back. Your account and goals are loaded. "
                    f"Type [bold {_ACCENT}]/help[/bold {_ACCENT}] for commands."
                    f"[/{_DIM_TEXT}]",
                    border_style=f"dim {_ACCENT_DEEP}",
                    padding=(0, 1),
                )
            )
    else:
        # CSV path: data is already loaded and summarized — go straight to REPL
        _CONSOLE.print(
            Panel(
                f"[{_DIM_TEXT}]Data loaded. Type [bold {_ACCENT}]/help[/bold {_ACCENT}] "
                f"for commands or start chatting.[/{_DIM_TEXT}]",
                border_style=f"dim {_ACCENT_DEEP}",
                padding=(0, 1),
            )
        )

    while True:
        try:
            user_input = _CONSOLE.input(
                f"\n[bold {_ACCENT}]›[/bold {_ACCENT}] "
                f"[{_DIM_TEXT}]you[/{_DIM_TEXT}]  "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            _CONSOLE.print(f"\n[{_DIM_TEXT}]Goodbye.[/{_DIM_TEXT}]")
            break

        if not user_input:
            continue

        # ── Slash commands ─────────────────────────────────────────────────────
        if user_input.startswith("/"):
            parts = user_input.split()
            cmd = parts[0].lower()

            if cmd in {"/quit", "/exit", "/q"}:
                _CONSOLE.print(f"[{_DIM_TEXT}]Goodbye.[/{_DIM_TEXT}]")
                break

            elif cmd == "/help":
                _render_help()

            elif cmd == "/setup":
                _render_setup_help()

            elif cmd == "/clear":
                _CONSOLE.clear()
                _render_banner()

            elif cmd == "/model":
                llm = _cmd_model(llm)

            elif cmd == "/account":
                _cmd_account(bank)

            elif cmd == "/split":
                _cmd_split(conn, _USER_ID)

            elif cmd == "/goal":
                _cmd_goal(conn, _USER_ID)

            elif cmd == "/fire":
                _cmd_fire(parts[1:], bank, conn)

            elif cmd == "/txn-add":
                _cmd_txn_add(bank, conn)

            elif cmd == "/txn-remove":
                _cmd_txn_remove(conn, bank, parts)

            elif cmd == "/txn-edit":
                _cmd_txn_edit(conn, bank, parts)

            elif cmd == "/import":
                sub = parts[1].lower() if len(parts) > 1 else "run"
                if sub == "preview":
                    _cmd_import_preview(parts)
                else:
                    _cmd_import_run(conn, bank, parts)

            elif cmd == "/import-preview" and len(parts) >= 2:
                _cmd_import_preview(["/import", "preview", parts[1]])  # legacy alias

            elif cmd == "/import-rollback":
                _cmd_import_rollback(conn, bank, parts)

            elif cmd == "/import-mapping":
                _cmd_import_mapping(conn, parts)

            elif cmd == "/review-categories":
                _cmd_review_categories(conn)

            elif cmd == "/cat-run":
                _cmd_cat_run(conn, llm)

            elif cmd == "/cat-accept":
                _cmd_cat_accept(conn, parts)

            elif cmd == "/cat-reject":
                _cmd_cat_reject(conn, parts)

            else:
                _CONSOLE.print(
                    f"[{_DIM_TEXT}]Unknown command: "
                    f"[bold]{cmd}[/bold]. "
                    f"Type [bold {_ACCENT}]/help[/bold {_ACCENT}] "
                    f"for available commands.[/{_DIM_TEXT}]"
                )
            continue

        # ── Agent call ─────────────────────────────────────────────────────────
        try:
            with _CONSOLE.status(
                f"[{_DIM_TEXT}]thinking…[/{_DIM_TEXT}]",
                spinner="dots",
                spinner_style=_ACCENT,
            ):
                response = handle_message(
                    llm=llm,
                    conn=conn,
                    user_id=_USER_ID,
                    conversation_id=_CONV_ID,
                    user_message=user_input,
                )
            _render_response(response)
        except KeyboardInterrupt:
            _CONSOLE.print(f"\n[{_DIM_TEXT}]Cancelled.[/{_DIM_TEXT}]")
        except Exception as exc:
            _CONSOLE.print(
                f"[bold red]Error:[/bold red] [red]{exc}[/red]"
            )


if __name__ == "__main__":
    main()

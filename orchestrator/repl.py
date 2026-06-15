#!/usr/bin/env python3
"""
Polished TUI REPL for the LUCID personal finance agent.

Presentation layer only — no business logic lives here.
router.handle_message() returns plain text; this file is solely responsible
for colors, panels, spinners, and every other terminal detail.

The router is client-agnostic: the same core serves this REPL, Telegram,
and a future web UI without modification.

Run:
    python -m orchestrator.repl
    python -m orchestrator.repl gpt-4o      # optional model override

    export ANTHROPIC_API_KEY=sk-ant-...     # required for default Claude model
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import pyfiglet
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from db.db_schema import init_db
from llm.config import build_adapter
from orchestrator.router import handle_message

# ── Session constants ──────────────────────────────────────────────────────────

_USER_ID = "demo-user-1"
_CONV_ID  = "demo-conv-1"

# ── Color palette ──────────────────────────────────────────────────────────────

# Banner gradient: bright cyan at the top, deep blue at the bottom
_BANNER_GRADIENT = [
    "#67e8f9",  # cyan-300   — top
    "#38bdf8",  # sky-400
    "#0ea5e9",  # sky-500
    "#3b82f6",  # blue-500
    "#2563eb",  # blue-600   — bottom
]

_ACCENT       = "#38bdf8"   # sky-400  — prompts, panel borders, slash highlights
_ACCENT_DEEP  = "#1d4ed8"   # blue-700 — response panel border
_RULE_COLOR   = "#0e7490"   # teal     — horizontal rules
_DIM_TEXT     = "#64748b"   # slate-500
_DIMMER_TEXT  = "#334155"   # slate-700

_CONSOLE = Console()

# ── Demo seed data ─────────────────────────────────────────────────────────────

_DEMO_TRANSACTIONS: list[tuple[str, float, str | None]] = [
    # Income (3 months of salary)
    ("Salary ACME AG",           5200.00,  None),
    ("Salary ACME AG",           5200.00,  None),
    ("Salary ACME AG",           5200.00,  None),
    # Needs
    ("Miete Zurich",            -1800.00, "need"),
    ("Helsana",                  -420.00, "need"),
    ("Coop",                     -480.00, "need"),
    ("Migros",                   -220.00, "need"),
    ("SBB Halbtax",              -180.00, "need"),
    ("Swisscom",                  -79.00, "need"),
    ("Coop",                     -155.00, "need"),
    ("EWZ Strom",                 -62.00, "need"),
    # Wants
    ("Netflix",                   -13.00, "want"),
    ("Spotify",                   -10.00, "want"),
    ("Starbucks",                 -42.00, "want"),
    ("Restaurant Helvetia",       -68.00, "want"),
    ("Zara",                      -89.00, "want"),
    ("Kino Kosmos",               -30.00, "want"),
    ("Starbucks",                 -14.00, "want"),
    ("Tibits",                    -25.00, "want"),
    ("Amazon.de",                 -55.00, "want"),
    # Savings
    ("VIAC 3a",                  -400.00, "savings"),
    ("Swissquote",               -200.00, "savings"),
]


# ── Banner ─────────────────────────────────────────────────────────────────────

def _render_banner() -> None:
    """ASCII-art title with a cyan → blue vertical gradient, plus subtitle."""
    art = pyfiglet.figlet_format("LUCID AGENT", font="slant")
    art_lines = art.rstrip("\n").split("\n")

    # Only colour non-blank lines; distribute gradient evenly across them.
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
        f"[{_DIM_TEXT}]Personal finance assistant[/{_DIM_TEXT}]",
        justify="center",
    )
    _CONSOLE.print(
        f"[{_DIMMER_TEXT}]type "
        f"[bold {_ACCENT}]/help[/bold {_ACCENT}] for commands · "
        f"[bold {_ACCENT}]/quit[/bold {_ACCENT}] to exit"
        f"[/{_DIMMER_TEXT}]",
        justify="center",
    )
    _CONSOLE.print(Rule(style=f"dim {_RULE_COLOR}"))
    _CONSOLE.print()


# ── Slash-command rendering ────────────────────────────────────────────────────

def _render_help() -> None:
    body = Text()
    body.append("Commands\n\n", style="bold")
    for cmd, desc in (
        ("/help ", "show this message"),
        ("/clear", "clear the screen (session continues)"),
        ("/quit ", "exit"),
    ):
        body.append(f"  {cmd}   ", style=f"bold {_ACCENT}")
        body.append(desc + "\n",   style="")

    _CONSOLE.print(Panel(
        body,
        title=f"[bold {_ACCENT}]help[/bold {_ACCENT}]",
        border_style=f"dim {_ACCENT_DEEP}",
        padding=(0, 1),
    ))


# ── Agent response ─────────────────────────────────────────────────────────────

def _render_response(text: str) -> None:
    """Render the agent's plain-text response in a styled panel.

    Switches to rich Markdown rendering when the response contains markdown
    syntax (headers, bold, fenced code, tables, bullet lists).
    """
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


# ── REPL loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    model_override = sys.argv[1] if len(sys.argv) > 1 else None

    _render_banner()

    # Provider selection: CLI arg → auto-detect → interactive wizard
    llm = build_adapter(model_override)
    _CONSOLE.print(
        f"[{_DIMMER_TEXT}]provider: {llm.model}[/{_DIMMER_TEXT}]\n",
        justify="center",
    )

    conn = init_db(":memory:")
    _seed_demo_data(conn)

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
            cmd = user_input.split()[0].lower()
            if cmd in {"/quit", "/exit", "/q"}:
                _CONSOLE.print(f"[{_DIM_TEXT}]Goodbye.[/{_DIM_TEXT}]")
                break
            elif cmd == "/help":
                _render_help()
            elif cmd == "/clear":
                _CONSOLE.clear()
                _render_banner()
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

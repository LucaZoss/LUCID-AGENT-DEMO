"""
Budget Onboarding — deterministic HITL flow (no LLM).

Runs after the ETL Loader and Labeller when no budget categories have been
assigned yet. Guides the user through four steps:

  1. Income identification  — mark the account as income-bearing
  2. Net balance (optional) — user inputs total capital / savings
  3. Needs classification   — user picks which line_categories are essentials
  4. Auto-classify rest     — remaining outflows → want; credits → savings

Usage:
    from agents.budget_onboarding.agent import run_budget_onboarding
    run_budget_onboarding(conn, user_id, account_id, console)
"""

from __future__ import annotations

import sqlite3

from agents.budget_onboarding import tools as _tools
from ingest.csv_normalize import parse_decimal


def run_budget_onboarding(
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
    console,
) -> None:
    """Interactive budget onboarding. Writes category to transactions."""
    from rich.table import Table

    console.print(
        "\n[bold cyan]━━  Budget Onboarding  ━━[/bold cyan]\n"
        "[dim]Your transactions don't have budget categories yet.\n"
        "Let's assign needs / wants / savings in four quick steps.[/dim]\n"
    )

    # ── Step 1: Income ────────────────────────────────────────────────────────
    console.print("[bold]Step 1 / 4 — Income[/bold]")
    income_data = _tools.fetch_income_candidates(conn, user_id)
    groups = income_data["groups"]

    if groups:
        tbl = Table(box=None, show_header=True, padding=(0, 1))
        tbl.add_column("#", style="bold cyan", width=4)
        tbl.add_column("Merchant", style="bold", min_width=28)
        tbl.add_column("Occurrences", justify="right", style="dim")
        tbl.add_column("Total CHF", justify="right")
        for i, g in enumerate(groups, 1):
            tbl.add_row(
                str(i),
                g["merchant"],
                str(g["count"]),
                f"[green]+{g['total_chf']:,.2f}[/green]",
            )
        console.print(tbl)
        console.print(
            f"  Total inflow: [green]+CHF {income_data['total_inflow_chf']:,.2f}[/green]\n"
        )
    else:
        console.print("  [dim]No credit (inflow) transactions found.[/dim]\n")

    try:
        from rich.prompt import Confirm
        mark_income = Confirm.ask(
            "  Mark this account as income-bearing "
            "(salary / regular deposits present)?",
            default=True,
        )
    except (EOFError, KeyboardInterrupt):
        mark_income = True

    if mark_income:
        _tools.apply_income_account(conn, user_id, account_id)
        console.print("  [green]Account marked as income-bearing.[/green]\n")
    else:
        console.print("  [dim]Skipped — income flag not set.[/dim]\n")

    # ── Step 2: Net balance (optional) ────────────────────────────────────────
    console.print("[bold]Step 2 / 4 — Current savings / capital (optional)[/bold]")
    console.print(
        "  Enter your total savings or capital today in CHF.\n"
        "  [dim]This helps compute goal feasibility. Press Enter to skip.[/dim]\n"
    )
    try:
        raw_bal = console.input("  Capital (CHF, Enter to skip) › ").strip()
    except (EOFError, KeyboardInterrupt):
        raw_bal = ""

    if raw_bal:
        amount = parse_decimal(raw_bal)
        if amount is not None:
            _tools.set_capital_balance(conn, user_id, account_id, amount)
            console.print(f"  [green]Capital set to CHF {amount:,.2f}[/green]\n")
        else:
            console.print("  [yellow]Could not parse amount — skipped.[/yellow]\n")
    else:
        console.print("  [dim]Skipped.[/dim]\n")

    # ── Step 3: Needs classification ──────────────────────────────────────────
    console.print("[bold]Step 3 / 4 — Needs (essentials)[/bold]")
    cat_data = _tools.fetch_outflow_line_categories(conn, user_id)
    categories = cat_data["categories"]

    if not categories:
        console.print("  [dim]No outflow transactions found — skipping.[/dim]\n")
        needs_selected: list[str] = []
    else:
        tbl2 = Table(box=None, show_header=True, padding=(0, 1))
        tbl2.add_column("#", style="bold cyan", width=4)
        tbl2.add_column("Category", style="bold", min_width=28)
        tbl2.add_column("Txns", justify="right", style="dim")
        tbl2.add_column("Total CHF", justify="right")
        tbl2.add_column("Suggested", style="dim")
        for i, c in enumerate(categories, 1):
            tbl2.add_row(
                str(i),
                c["line_category"],
                str(c["count"]),
                f"[red]{c['total_chf']:,.2f}[/red]",
                "✓ need" if c["suggested_need"] else "",
            )
        console.print(tbl2)

        pre_checked = [
            str(i) for i, c in enumerate(categories, 1) if c["suggested_need"]
        ]
        default_hint = ",".join(pre_checked) if pre_checked else "none"
        console.print(
            f"\n  [dim]Pre-selected essentials: {default_hint}[/dim]\n"
            "  Enter the numbers of NEEDS categories (comma-separated).\n"
            "  Press Enter to use the pre-selection, or type new numbers.\n"
        )
        try:
            raw_needs = console.input("  Needs › ").strip()
        except (EOFError, KeyboardInterrupt):
            raw_needs = ""

        chosen_input = raw_needs if raw_needs else default_hint
        chosen_indices: list[int] = []
        for tok in chosen_input.split(","):
            tok = tok.strip()
            if tok.isdigit():
                idx = int(tok) - 1
                if 0 <= idx < len(categories):
                    chosen_indices.append(idx)

        needs_selected = [categories[i]["line_category"] for i in chosen_indices]
        if needs_selected:
            result = _tools.apply_category_by_line_categories(
                conn, user_id, needs_selected, "need"
            )
            console.print(
                f"  [green]{result['updated']} transaction(s) marked as needs.[/green]\n"
            )
        else:
            console.print("  [dim]No needs selected.[/dim]\n")

    # ── Step 4: Auto-classify the rest ────────────────────────────────────────
    console.print("[bold]Step 4 / 4 — Auto-classifying remaining transactions[/bold]")
    wants_result = _tools.apply_remaining_outflows_as_wants(conn, user_id)
    savings_result = _tools.apply_remaining_credits_as_savings(conn, user_id)

    console.print(
        f"  [dim]Wants (outflows not marked as needs):[/dim]  "
        f"[yellow]{wants_result['updated']}[/yellow] transactions\n"
        f"  [dim]Savings / refunds (remaining credits):[/dim]  "
        f"[cyan]{savings_result['updated']}[/cyan] transactions\n"
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    row = conn.execute(
        "SELECT "
        "  SUM(CASE WHEN t.category='need'    THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN t.category='want'    THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN t.category='savings' THEN 1 ELSE 0 END) "
        "FROM transactions t JOIN accounts a ON t.account_id = a.id "
        "WHERE a.user_id = ?",
        (user_id,),
    ).fetchone()
    n_need, n_want, n_sav = (row[0] or 0), (row[1] or 0), (row[2] or 0)

    console.print(
        "[bold cyan]━━  Onboarding complete  ━━[/bold cyan]\n"
        f"  Needs:    [bold]{n_need}[/bold] transactions\n"
        f"  Wants:    [bold]{n_want}[/bold] transactions\n"
        f"  Savings:  [bold]{n_sav}[/bold] transactions\n\n"
        "  [dim]You can adjust categories any time with [bold]/cat-accept[/bold] "
        "or by chatting with the agent.[/dim]"
    )

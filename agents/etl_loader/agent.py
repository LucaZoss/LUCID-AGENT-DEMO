"""
ETL Loader Agent — Agent 1 in the refactored LUCID pipeline.

Scout Pattern:
  1. Scan folder for CSV files.
  2. For each file, check complexity and look up the format profile by header fingerprint.
  3. If profile is confirmed with use_count >= 2: auto-apply silently.
  4. Otherwise: show columns, ask user to confirm or correct mapping (HITL).
  5. Import the file; save/update the format profile.
  6. Hand off to the Labeller Agent.

Usage:
    from agents.etl_loader.agent import run_etl_loader_agent
    summary = run_etl_loader_agent(llm, conn, user_id, account_id, csv_folder, console)
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from llm.provider import LLMProvider, ToolCall

from agents.etl_loader import tools as _tools


# ── Deterministic pipeline (no LLM) ──────────────────────────────────────────

def _print_import_summary(
    console,
    conn: sqlite3.Connection,
    batch_ids: list[str],
) -> None:
    """Print a describe-style summary of the just-imported transactions."""
    if not batch_ids:
        return

    placeholders = ",".join("?" * len(batch_ids))
    rows = conn.execute(
        f"""
        SELECT t.ts, t.merchant, t.amount, t.line_category
        FROM transactions t
        WHERE t.import_batch_id IN ({placeholders})
        ORDER BY t.ts
        """,
        batch_ids,
    ).fetchall()

    if not rows:
        return

    from collections import Counter

    dates   = [r[0][:10] for r in rows if r[0]]
    amounts = [r[2] for r in rows if r[2] is not None]
    cats    = [r[3] or "(uncategorized)" for r in rows]
    merchants = Counter(r[1] for r in rows if r[1])
    cat_counts = Counter(cats)

    console.print("\n[bold cyan]━━  Import summary  ━━[/bold cyan]\n")
    console.print(f"  Transactions : [bold]{len(rows)}[/bold]")
    if dates:
        console.print(f"  Date range   : {min(dates)} → {max(dates)}")
    if amounts:
        outflow = sum(a for a in amounts if a < 0)
        inflow  = sum(a for a in amounts if a > 0)
        mean    = sum(amounts) / len(amounts)
        console.print(f"  Amount (CHF) :")
        console.print(f"    total outflow  [red]{outflow:>10.2f}[/red]")
        if inflow:
            console.print(f"    total inflow   [green]{inflow:>10.2f}[/green]")
        console.print(f"    mean           {mean:>10.2f}")
        console.print(f"    min            {min(amounts):>10.2f}")
        console.print(f"    max            {max(amounts):>10.2f}")
    if merchants:
        console.print(f"\n  Top merchants:")
        for name, count in merchants.most_common(5):
            console.print(f"    {name:<32} {count}×")
    if cat_counts:
        console.print(f"\n  Categories:")
        for cat, count in cat_counts.most_common():
            console.print(f"    {cat:<32} {count}")
    console.print()


def _review_duplicates(
    console,
    conn: sqlite3.Connection,
    dup_rows: list[dict],
    account_id: str,
) -> None:
    """Show duplicate rows in a table and offer to force-insert them."""
    from rich.table import Table

    console.print(f"\n  [yellow]⚠  {len(dup_rows)} duplicate(s) skipped — already in DB:[/yellow]\n")

    tbl = Table(box=None, show_header=True, padding=(0, 2))
    tbl.add_column("#", style="bold cyan", width=3)
    tbl.add_column("Date", width=11)
    tbl.add_column("Merchant", min_width=24)
    tbl.add_column("Amount", justify="right", width=10)
    tbl.add_column("Category", style="dim")

    for idx, row in enumerate(dup_rows, 1):
        amt = row["amount"]
        amt_str = f"[red]{amt:.2f}[/red]" if amt < 0 else f"[green]{amt:.2f}[/green]"
        tbl.add_row(
            str(idx),
            row["date"],
            row["merchant"],
            amt_str,
            row.get("category") or "",
        )
    console.print(tbl)

    try:
        raw = console.input(
            "\n  Force-import duplicates? "
            "[dim]Enter row numbers (e.g. 1,3) or [bold]a[/bold]=all / [bold]n[/bold]=none (default)[/dim] › "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        raw = ""

    if not raw or raw == "n":
        console.print("  [dim]Duplicates skipped.[/dim]")
        return

    to_insert = dup_rows if raw == "a" else [
        dup_rows[int(i) - 1]
        for i in raw.split(",")
        if i.strip().isdigit() and 0 < int(i.strip()) <= len(dup_rows)
    ]

    if not to_insert:
        console.print("  [dim]No valid selection — duplicates skipped.[/dim]")
        return

    import uuid as _uuid
    forced = 0
    for row in to_insert:
        tid = f"csv-forced-{_uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO transactions("
            "id, account_id, amount, currency, merchant, category, line_category, "
            "ts, import_batch_id, external_fingerprint"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                account_id,
                row["amount"],
                row.get("currency", "CHF"),
                row["merchant"],
                None,
                row.get("line_category"),
                row["ts"],
                None,
                f"{row['fingerprint']}_forced_{tid}",
            ),
        )
        forced += 1
    conn.commit()
    console.print(f"  [green]✓ {forced} duplicate(s) force-imported.[/green]")


def run_etl_pipeline(
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
    csv_folder: str,
    console,
) -> str:
    """Deterministic ETL pipeline — zero LLM calls.

    Sequence per file:
      1. Check saved format profile (auto-apply if confirmed × ≥ 2)
      2. Otherwise run HITL column mapping (4 fields: date, merchant, amount, category)
      3. Import; save/update format profile
    After all files: print a describe-style summary and return.
    """
    console.print("\n[bold cyan]━━  ETL Loader: importing CSV files  ━━[/bold cyan]\n")

    scan = _tools.scan_folder(csv_folder)
    if not scan.get("ok"):
        msg = f"Cannot scan folder: {scan.get('error')}"
        console.print(f"[red]{msg}[/red]")
        return msg

    files: list[str] = scan.get("files", [])
    if not files:
        msg = "No CSV files found in folder."
        console.print(f"[dim]{msg}[/dim]")
        return msg

    console.print(f"  Found [bold]{len(files)}[/bold] file(s)\n")

    all_batch_ids: list[str] = []

    for file_path in files:
        from pathlib import Path
        fname = Path(file_path).name
        console.print(f"[bold]─── {fname} ───[/bold]")

        profile = _tools.lookup_format_profile(conn, user_id, file_path)

        if profile.get("auto_apply"):
            console.print(f"  [dim]Profile '{profile.get('source_label', 'saved')}' auto-applied.[/dim]")
            column_map  = profile["column_map"]
            sign_rule   = profile["sign_rule"]
            encoding    = profile.get("encoding", "utf-8")
            delimiter   = profile.get("delimiter", ",")
            category_col = profile.get("category_col")
        else:
            result = _tools.show_columns_ask_user(
                file_path, console, llm=None, conn=conn, user_id=user_id
            )
            if not result.get("ok") or result.get("skipped"):
                console.print(f"  [yellow]Skipped.[/yellow]\n")
                continue
            column_map   = result["column_map"]
            sign_rule    = result["sign_rule"]
            encoding     = result.get("encoding", "utf-8")
            delimiter    = result.get("delimiter", ",")
            category_col = result.get("category_col")

        imp = _tools.import_file(
            conn, user_id, account_id,
            file_path=file_path,
            column_map=column_map,
            sign_rule=sign_rule,
            encoding=encoding,
            delimiter=delimiter,
            category_col=category_col,
        )

        if imp.get("ok"):
            n = imp.get("rows_inserted", 0)
            d = imp.get("rows_skipped_duplicate", 0)
            console.print(f"  [green]✓ {n} rows imported[/green]  ({d} dupes skipped)")
            invalid = imp.get("rows_skipped_invalid", 0)
            transfer = imp.get("rows_skipped_transfer", 0)
            if invalid:
                console.print(
                    f"  [yellow]⚠  {invalid} row(s) skipped — unparseable date or amount.[/yellow]"
                )
            if transfer:
                console.print(
                    f"  [dim]{transfer} row(s) skipped — matched a skip pattern.[/dim]"
                )
            if n == 0 and invalid > 0 and sign_rule == "debit_credit":
                console.print(
                    "  [dim]Hint: if both Debit/Credit columns showed 0 % fill, "
                    "try re-importing using the 'Individual amount' column instead.[/dim]"
                )
            if imp.get("batch_id"):
                all_batch_ids.append(imp["batch_id"])
            _tools.save_format_profile(
                conn, user_id,
                file_path=file_path,
                column_map=column_map,
                sign_rule=sign_rule,
                encoding=encoding,
                delimiter=delimiter,
                category_col=category_col,
            )
            dup_rows = imp.get("duplicate_rows") or []
            if dup_rows:
                _review_duplicates(console, conn, dup_rows, imp["account_id"])
        else:
            console.print(f"  [red]✗ {imp.get('message', 'import failed')}[/red]")

        console.print()

    _print_import_summary(console, conn, all_batch_ids)
    return f"ETL complete — {len(all_batch_ids)} file(s) imported."

_SYSTEM = """\
You are the ETL Loader Agent for LUCID personal finance.
Your job: discover CSV files in a folder, confirm their column mapping, import them, and save format profiles.

Follow these steps for each file:

1. Call scan_folder to list CSV files.
2. For each file: call check_complexity.
3. Call lookup_format_profile to check memory.
   - If found with auto_apply=true: import immediately, show one-line confirmation.
   - Otherwise: call show_columns_ask_user to display columns and get user confirmation.
4. Call import_file with the confirmed mapping.
5. Call save_format_profile to persist the mapping for future use.
6. When all files are done, produce a short summary for the user.

Rules:
- Keep messages short; this is a terminal UI.
- Never invent column names — only use names from the lookup or show_columns result.
- Always call show_columns_ask_user when a profile is not found or not auto-applicable.
- Currency is CHF; amounts are negative for outflows. Positive amounts are credits (refunds, salary, transfers in).
- When a CSV has separate debit and credit columns, use sign_rule="debit_credit" and set column_map keys "debit" and "credit" (not "amount").
- Do not discuss budgets or goals — that is the REPL's job.
"""

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "scan_folder",
            "description": "List all .csv files in the given folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Absolute path to the CSV folder.",
                    }
                },
                "required": ["folder_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_complexity",
            "description": "Analyze a file and return its complexity and parse strategy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_format_profile",
            "description": (
                "Look up a saved column-mapping profile for a file by its header fingerprint. "
                "Returns auto_apply=true if the profile is confirmed and use_count >= 2."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_columns_ask_user",
            "description": (
                "Display all CSV columns with samples and run the interactive HITL mapping dialog. "
                "Call this when no auto-applicable profile exists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "import_file",
            "description": "Import a CSV file using the confirmed column mapping.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "column_map": {
                        "type": "object",
                        "description": "Lucid field → CSV column name.",
                        "additionalProperties": {"type": "string"},
                    },
                    "sign_rule": {
                        "type": "string",
                        "enum": ["single_amount", "single_amount_flipped", "debit_credit"],
                    },
                    "encoding": {"type": "string"},
                    "delimiter": {"type": "string"},
                    "category_col": {"type": "string"},
                },
                "required": ["file_path", "column_map", "sign_rule"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_format_profile",
            "description": "Persist a confirmed format profile for future auto-apply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "column_map": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "sign_rule": {"type": "string"},
                    "encoding": {"type": "string"},
                    "delimiter": {"type": "string"},
                    "source_label": {
                        "type": "string",
                        "description": "User-visible format name e.g. 'Mastercard CH'.",
                    },
                    "category_col": {"type": "string"},
                },
                "required": ["file_path", "column_map", "sign_rule"],
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
    account_id: str,
    console,
    llm,
) -> Any:
    if name == "scan_folder":
        return _tools.scan_folder(str(args.get("folder_path", "")))

    if name == "check_complexity":
        return _tools.check_complexity(str(args.get("file_path", "")))

    if name == "lookup_format_profile":
        return _tools.lookup_format_profile(conn, user_id, str(args.get("file_path", "")))

    if name == "show_columns_ask_user":
        return _tools.show_columns_ask_user(
            str(args.get("file_path", "")),
            console,
            llm,
            conn=conn,
            user_id=user_id,
        )

    if name == "import_file":
        return _tools.import_file(
            conn,
            user_id,
            account_id,
            file_path=str(args.get("file_path", "")),
            column_map=dict(args.get("column_map") or {}),
            sign_rule=str(args.get("sign_rule", "single_amount")),
            encoding=str(args.get("encoding", "utf-8")),
            delimiter=str(args.get("delimiter", ",")),
            category_col=args.get("category_col") or None,
        )

    if name == "save_format_profile":
        return _tools.save_format_profile(
            conn,
            user_id,
            file_path=str(args.get("file_path", "")),
            column_map=dict(args.get("column_map") or {}),
            sign_rule=str(args.get("sign_rule", "single_amount")),
            encoding=str(args.get("encoding", "utf-8")),
            delimiter=str(args.get("delimiter", ",")),
            source_label=args.get("source_label") or None,
            category_col=args.get("category_col") or None,
        )

    return {"ok": False, "error": f"unknown tool: {name}"}


def run_etl_loader_agent(
    llm: LLMProvider,
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
    csv_folder: str,
    console,
    *,
    max_iterations: int = 40,
) -> str:
    """Run the ETL Loader Agent interactively. Returns final summary text."""
    console.print("\n[bold cyan]━━  ETL Loader: importing CSV files  ━━[/bold cyan]")
    console.print(
        "[dim]I'll discover your CSV files, confirm the column mapping, "
        "and import the data.[/dim]\n"
    )

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Please import all CSV files from this folder: {csv_folder}\n"
                "Scan the folder, check each file's format memory, confirm mapping "
                "with me when needed, import all files, and save format profiles."
            ),
        }
    ]

    final_text = "ETL import complete."

    for _ in range(max_iterations):
        try:
            resp = llm.complete(
                system=_SYSTEM,
                messages=messages,
                tools=_TOOLS,
            )
        except Exception as exc:
            console.print(f"\n[bold red]  ETL Loader: LLM error — {exc}[/bold red]")
            console.print("[dim]  Check your API key / provider and retry.[/dim]")
            return f"ETL import aborted: {exc}"

        if resp.content:
            console.print(
                f"\n[bold cyan]  ETL Loader:[/bold cyan]\n  {resp.content}"
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
                tc.name, tc.arguments, conn, user_id, account_id, console, llm
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    return final_text

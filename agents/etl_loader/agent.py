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
- Currency is CHF; amounts are negative for outflows.
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

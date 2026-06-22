"""
Database Manager Agent — Agent 1 in the LUCID onboarding flow.

Handles CSV discovery, schema confirmation, import, transaction categorization,
and summary via a conversational LLM loop. The agent uses the ask_user tool to
pause and collect typed input, so it genuinely teams with the user to set up
the source of truth before handing off to Agent 2 (Budget Planner).

Usage:
    from agents.db_manager import run_db_manager_agent
    summary = run_db_manager_agent(llm, conn, user_id, account_id, csv_folder, console)
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from llm.provider import LLMProvider, ToolCall

from agents import db_manager_tools as tools_module

_SYSTEM = """\
You are the Database Manager Agent for LUCID personal finance.
Your job: help the user import their bank CSV files and build the source of truth.

Work through these steps in order:
1. Call scan_csv_folder to discover all CSV files.
2. For each file, call analyze_csv_file to understand its structure.
3. Call ask_user to show what was auto-detected and confirm it:
   - Summarise the detected mapping in plain English (e.g. "Date → Buchungsdatum, Merchant → Begünstigter, Amount → Betrag, sign rule: negative = outflow").
   - If anything is ambiguous or missing, ask the user to pick the right column.
4. Call import_file with the confirmed mapping (pass encoding and delimiter from analyze result).
5. Call propose_categories_for_batch to classify transactions into need/want/savings.
6. Call ask_user to present the grouped results:
   - Show each group: "I'll tag [merchants] as [bucket / line]."
   - Ask: "Does this look right, or would you like to change anything?"
   - If the user makes corrections, note them but still call accept_category_proposals
     with the full list — the user can fine-tune later with /cat-accept.
7. Call accept_category_proposals with all proposal_ids from step 5.
8. Call generate_import_summary and present the results to the user.

Rules:
- Keep messages short; this is a terminal UI.
- Always call ask_user before import and before accepting categories.
- Never invent column names — only use names from the analyze result.
- Currency is CHF; amounts are negative for outflows.
- Do not discuss budgets or goals — that is Agent 2's job.
"""

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Display a message or question to the user and wait for their typed reply. "
                "Use this to confirm mappings, categories, or any uncertain data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The message or question to show the user.",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_csv_folder",
            "description": "List all .csv files in a folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Absolute or ~ path to the folder containing CSV exports.",
                    }
                },
                "required": ["folder_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_csv_file",
            "description": (
                "Preview one CSV file: returns column headers, 3 sample rows, and the "
                "auto-detected column mapping (date / merchant / amount / sign_rule)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the CSV file.",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "import_file",
            "description": (
                "Import a CSV file using the confirmed column mapping. "
                "Call only after the user has confirmed the mapping via ask_user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the CSV file.",
                    },
                    "column_map": {
                        "type": "object",
                        "description": (
                            "Maps Lucid field names to actual CSV column names. "
                            "Required keys: 'date', 'merchant', and either 'amount' "
                            "or both 'debit'/'credit'. Use exact column names from analyze_csv_file."
                        ),
                        "additionalProperties": {"type": "string"},
                    },
                    "sign_rule": {
                        "type": "string",
                        "enum": ["single_amount", "single_amount_flipped", "debit_credit"],
                        "description": (
                            "single_amount: one column, negative = outflow. "
                            "single_amount_flipped: one column, positive = outflow. "
                            "debit_credit: separate debit (outflow) and credit (inflow) columns."
                        ),
                    },
                    "encoding": {
                        "type": "string",
                        "description": "File encoding from analyze_csv_file (e.g. utf-8, iso-8859-1).",
                    },
                    "delimiter": {
                        "type": "string",
                        "description": "Column delimiter from analyze_csv_file (e.g. ',' or ';').",
                    },
                    "category_col": {
                        "type": "string",
                        "description": "Optional: CSV column containing raw bank category labels.",
                    },
                },
                "required": ["file_path", "column_map", "sign_rule"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_categories_for_batch",
            "description": (
                "Classify imported transactions into need/want/savings buckets using "
                "deterministic rules and create pending proposals. Returns groups of "
                "merchants with proposed categories so you can present them to the user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max transactions to process in this batch (default 50).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "accept_category_proposals",
            "description": (
                "Accept a list of category proposals, writing the categories to the "
                "transactions table. Call after the user has confirmed the groupings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Proposal IDs to accept (from propose_categories_for_batch).",
                    }
                },
                "required": ["proposal_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_import_summary",
            "description": "Generate final aggregate stats. Call this as the last step.",
            "parameters": {"type": "object", "properties": {}},
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
) -> Any:
    # ask_user: intercept here so the tool can block on console input
    if name == "ask_user":
        question = str(args.get("question", ""))
        console.print(f"\n[bold cyan]  Database Manager Agent:[/bold cyan]\n  {question}")
        try:
            answer = console.input("\n  [bold]You:[/bold] › ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        return {"answer": answer}

    if name == "scan_csv_folder":
        return tools_module.scan_csv_folder(str(args.get("folder_path", "")))

    if name == "analyze_csv_file":
        return tools_module.analyze_csv_file(str(args.get("file_path", "")))

    if name == "import_file":
        return tools_module.import_file(
            file_path=str(args.get("file_path", "")),
            column_map=dict(args.get("column_map") or {}),
            sign_rule=str(args.get("sign_rule", "single_amount")),
            account_id=account_id,
            user_id=user_id,
            conn=conn,
            category_col=args.get("category_col") or None,
            encoding=str(args.get("encoding", "utf-8")),
            delimiter=str(args.get("delimiter", ",")),
        )

    if name == "propose_categories_for_batch":
        return tools_module.propose_categories_for_batch(
            conn, user_id, int(args.get("limit", 50))
        )

    if name == "accept_category_proposals":
        return tools_module.accept_category_proposals(
            conn, user_id, list(args.get("proposal_ids") or [])
        )

    if name == "generate_import_summary":
        return tools_module.generate_import_summary(conn, user_id)

    return {"ok": False, "error": f"unknown tool: {name}"}


def run_db_manager_agent(
    llm: LLMProvider,
    conn: sqlite3.Connection,
    user_id: str,
    account_id: str,
    csv_folder: str,
    console,
    *,
    max_iterations: int = 40,
) -> str:
    """Delegated to agents.etl_loader.agent for backward compatibility."""
    from agents.etl_loader.agent import run_etl_loader_agent
    return run_etl_loader_agent(
        llm, conn, user_id, account_id, csv_folder, console,
        max_iterations=max_iterations,
    )

"""
JSON-schema tool definitions exposed to the LLM during skill execution.

These are the deterministic Phase-2 tools from tools/ wrapped in OpenAI-style
function schemas. The router dispatches actual Python calls; this module is
purely the schema the model sees.

Add a definition here whenever a new deterministic tool should be callable
during the agent loop. Never add LLM calls or side-effectful operations here.
"""

from __future__ import annotations

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "compute_current_split",
            "description": (
                "Compute the user's actual needs / wants / savings spending ratios "
                "from real ledger transactions. Returns income_chf, each bucket in "
                "CHF, and percentages. ALWAYS call this before advising on budgets "
                "or frameworks — never assume ratios."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Look-back window in days (default 90).",
                        "default": 90,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_goal_status",
            "description": (
                "Return the user's active goal and feasibility metrics: "
                "goal type (open / target), amount, deadline, "
                "required monthly saving, and whether they are on track."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dashboard_summary",
            "description": (
                "Assemble the full dashboard payload for a calendar period: "
                "split ratios, top-10 merchants, category breakdown, "
                "budget-vs-actual, and goal progress. "
                "Use when the user asks for an overview of their finances."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": (
                            "Calendar month to summarize, e.g. '2026-06'. "
                            "Defaults to the current month."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "categorize_merchant",
            "description": (
                "Deterministically categorize a merchant name as "
                "'need', 'want', or 'savings'. "
                "Use when the user asks where a specific purchase fits."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant": {
                        "type": "string",
                        "description": "Merchant name as it appears on the bank statement.",
                    },
                },
                "required": ["merchant"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transactions_by_bucket",
            "description": (
                "Return transactions filtered by budget label (need, want, or savings). "
                "Use when the user asks about spending in a specific budget category, "
                "e.g. 'show my needs', 'list my wants', 'what are my savings transfers'. "
                "Returns count and a list of matching transactions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket": {
                        "type": "string",
                        "enum": ["need", "want", "savings"],
                        "description": "The budget label to filter by.",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Look-back window in days (default 90).",
                        "default": 90,
                    },
                },
                "required": ["bucket"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transactions_by_category",
            "description": (
                "Return transactions filtered by raw bank category label "
                "(e.g. 'Lebensmittel', 'Restaurant', 'Versicherung'). "
                "Use when the user asks about a specific type of spending by its "
                "bank-assigned category name, not the need/want/savings bucket. "
                "Partial matches are supported (case-insensitive)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            "Bank category label to search for. "
                            "Partial strings work, e.g. 'groc' matches 'Groceries'."
                        ),
                    },
                    "days": {
                        "type": "integer",
                        "description": "Look-back window in days (default 90).",
                        "default": 90,
                    },
                },
                "required": ["category"],
            },
        },
    },
]

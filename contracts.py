"""
Shared dataclass contracts for the personal finance agent.

These are the data-transfer objects that cross layer boundaries — bank →
tools → LLM → dashboard. Keep them stable: downstream tools and the DB schema
mirror these shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class Transaction:
    id: str
    account_id: str
    amount: float        # negative = outflow, positive = inflow; CHF
    currency: str        # 'CHF' in the demo
    merchant: str
    category: str | None  # raw: 'need' | 'want' | 'savings' (legacy bucket)
    ts: datetime
    line_category: str | None = None        # raw: fine label e.g. rent, groceries
    normalized_category: str | None = None  # canonical taxonomy key e.g. 'groceries_food'
    import_batch_id: str | None = None
    external_fingerprint: str | None = None  # CSV dedupe key


@dataclass
class Account:
    id: str
    user_id: str
    name: str
    balance: float
    currency: str = "CHF"
    account_type: str = "checking"   # checking | credit_card | savings
    has_income: bool = False


@dataclass
class StructuredGoal:
    id: str
    user_id: str
    goal_type: str            # 'open' | 'target'
    engagement: str           # 'low' | 'high'
    amount: float | None = None
    target_date: date | None = None
    framework: str | None = None  # '50_30_20' | 'zero_based' | 'pay_first'
    active: bool = True


@dataclass
class Budget:
    id: str
    user_id: str
    allocations: dict[str, float]    # {"groceries": 600, "dining": 200, ...}
    target_ratios: dict[str, float]  # {"needs": 0.55, "wants": 0.25, "savings": 0.20}
    period: str                      # '2026-06'

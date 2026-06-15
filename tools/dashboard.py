"""
build_dashboard_payload — assembles the chart-ready data contract.

Lock this shape early; the UI renders exactly what is here. If you add or
rename a key, update the frontend contract at the same time.

All monetary values are in CHF. Percentages are 0–100 floats.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from contracts import Budget, StructuredGoal, Transaction
from tools.split import SplitResult, compute_split
from tools.feasibility import FeasibilityResult, compute_goal_feasibility
from tools.categorize import categorize_transaction


@dataclass
class MerchantSummary:
    merchant: str
    total_chf: float
    count: int
    category: str


@dataclass
class CategoryLine:
    category: str       # 'need' | 'want' | 'savings'
    total_chf: float
    pct_of_income: float


@dataclass
class BudgetVsActualLine:
    category: str
    budget_chf: float
    actual_chf: float
    pct_used: float     # actual / budget * 100
    over_budget: bool


@dataclass
class DashboardPayload:
    period: str                             # e.g. '2026-06'
    generated_at: datetime
    split: SplitResult
    top_merchants: list[MerchantSummary]    # top-10 by spend
    category_breakdown: list[CategoryLine]  # need / want / savings
    budget_vs_actual: list[BudgetVsActualLine] | None
    goal_progress: dict | None              # None when no goal supplied
    income_chf: float
    total_outflow_chf: float
    net_chf: float                          # income − outflow


def build_dashboard_payload(
    period: str,
    transactions: list[Transaction],
    budget: Budget | None = None,
    goal: StructuredGoal | None = None,
    current_savings: float = 0.0,
    monthly_income: float | None = None,
) -> DashboardPayload:
    """Assemble the full dashboard payload from the deterministic core.

    Args:
        period:          calendar period this snapshot covers, e.g. '2026-06'.
        transactions:    all transactions for the period (income + spending).
        budget:          optional; if supplied, budget_vs_actual is computed.
        goal:            optional; if supplied, goal_progress is computed.
        current_savings: cumulative savings toward the goal (CHF).
        monthly_income:  override for feasibility calc; derived from transactions
                         if not supplied (divided by months implied by the split).
    """
    split = compute_split(transactions)

    # ── Top merchants by spend ────────────────────────────────────────────────
    merchant_map: dict[str, dict] = defaultdict(lambda: {"total": 0.0, "count": 0, "category": "want"})
    for t in transactions:
        if t.amount >= 0:
            continue
        m = merchant_map[t.merchant]
        m["total"] += abs(t.amount)
        m["count"] += 1
        m["category"] = t.category if t.category is not None else categorize_transaction(t)

    top_merchants = sorted(
        [
            MerchantSummary(
                merchant=name,
                total_chf=round(v["total"], 2),
                count=v["count"],
                category=v["category"],
            )
            for name, v in merchant_map.items()
        ],
        key=lambda x: x.total_chf,
        reverse=True,
    )[:10]

    # ── Category breakdown ────────────────────────────────────────────────────
    category_breakdown = [
        CategoryLine("need",    split.needs_chf,   split.needs_pct),
        CategoryLine("want",    split.wants_chf,   split.wants_pct),
        CategoryLine("savings", split.savings_chf, split.savings_pct),
    ]

    # ── Budget vs actual ──────────────────────────────────────────────────────
    bva: list[BudgetVsActualLine] | None = None
    if budget is not None:
        cat_totals = {"need": split.needs_chf, "want": split.wants_chf, "savings": split.savings_chf}
        bva = []
        for cat, limit in budget.allocations.items():
            actual = cat_totals.get(cat, 0.0)
            pct_used = round(actual / limit * 100, 1) if limit else 0.0
            bva.append(BudgetVsActualLine(
                category=cat,
                budget_chf=round(limit, 2),
                actual_chf=round(actual, 2),
                pct_used=pct_used,
                over_budget=actual > limit,
            ))

    # ── Goal progress ─────────────────────────────────────────────────────────
    gp: dict | None = None
    if goal is not None:
        income_for_feasibility = monthly_income or split.income_chf
        feasibility: FeasibilityResult = compute_goal_feasibility(
            goal=goal,
            monthly_income=income_for_feasibility,
            current_savings=current_savings,
        )
        if goal.goal_type == "target" and goal.amount:
            pct_complete = round(current_savings / goal.amount * 100, 1)
        else:
            pct_complete = 0.0

        gp = {
            "goal_type":          goal.goal_type,
            "target_chf":         goal.amount,
            "target_date":        goal.target_date.isoformat() if goal.target_date else None,
            "saved_chf":          round(current_savings, 2),
            "pct_complete":       pct_complete,
            "required_monthly_chf": feasibility.required_monthly_chf,
            "on_track":           feasibility.on_track,
            "months_remaining":   feasibility.months_remaining,
        }

    total_outflow = round(split.needs_chf + split.wants_chf + split.explicit_savings_chf, 2)

    return DashboardPayload(
        period=period,
        generated_at=datetime.now(timezone.utc),
        split=split,
        top_merchants=top_merchants,
        category_breakdown=category_breakdown,
        budget_vs_actual=bva,
        goal_progress=gp,
        income_chf=split.income_chf,
        total_outflow_chf=total_outflow,
        net_chf=round(split.income_chf - total_outflow, 2),
    )

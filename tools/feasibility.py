"""
compute_goal_feasibility — pure date/arithmetic math, no LLM.

Answers: given what the user has saved so far and their monthly income,
can they hit their savings target by the deadline?

For open-ended goals (goal_type == 'open') the function computes a
"pay-yourself-first" suggested monthly contribution (10 % of income by default)
and always marks them as on_track — there's nothing to fall behind on without
a target.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from contracts import StructuredGoal

_DAYS_PER_MONTH = 30.4375   # average, avoids calendar arithmetic


@dataclass
class FeasibilityResult:
    goal_type: str              # 'open' | 'target'
    required_monthly_chf: float # CHF/month needed to reach the goal in time
    on_track: bool
    months_remaining: float     # for 'target' goals; 0.0 for 'open'
    still_needed_chf: float     # target - current_savings; 0.0 for 'open'
    suggested_rate_pct: float   # required_monthly / monthly_income * 100


def compute_goal_feasibility(
    goal: StructuredGoal,
    monthly_income: float,
    current_savings: float,
    reference_date: date | None = None,
) -> FeasibilityResult:
    """Return feasibility metrics for *goal*.

    Args:
        goal:            the user's StructuredGoal (from contracts).
        monthly_income:  gross monthly income in CHF.
        current_savings: amount already saved toward this goal in CHF.
        reference_date:  override "today" (useful in tests).

    Raises ValueError when monthly_income is zero or when a target goal
    has no amount or target_date set.
    """
    if monthly_income <= 0:
        raise ValueError(f"monthly_income must be positive; got {monthly_income}")

    today = reference_date or date.today()

    if goal.goal_type == "open":
        # Pay-yourself-first: suggest 10 % of income as a sustainable floor.
        suggested = round(monthly_income * 0.10, 2)
        return FeasibilityResult(
            goal_type="open",
            required_monthly_chf=suggested,
            on_track=True,            # open goals are always "on track"
            months_remaining=0.0,
            still_needed_chf=0.0,
            suggested_rate_pct=10.0,
        )

    # ── Target goal ──────────────────────────────────────────────────────────
    if goal.amount is None:
        raise ValueError("Target goal must have an amount set.")
    if goal.target_date is None:
        raise ValueError("Target goal must have a target_date set.")

    days_left = (goal.target_date - today).days
    months_remaining = max(0.0, days_left / _DAYS_PER_MONTH)
    still_needed = max(0.0, goal.amount - current_savings)

    if months_remaining == 0:
        # Deadline passed or today — either already done or failed.
        required_monthly = 0.0 if still_needed == 0 else float("inf")
    else:
        required_monthly = round(still_needed / months_remaining, 2)

    suggested_rate_pct = round(required_monthly / monthly_income * 100, 1)
    on_track = required_monthly <= monthly_income   # achievable within one month's income

    return FeasibilityResult(
        goal_type="target",
        required_monthly_chf=required_monthly,
        on_track=on_track,
        months_remaining=round(months_remaining, 1),
        still_needed_chf=round(still_needed, 2),
        suggested_rate_pct=suggested_rate_pct,
    )

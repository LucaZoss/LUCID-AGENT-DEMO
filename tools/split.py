"""
compute_split — pure math, no LLM.

Computes the needs / wants / savings split from a list of transactions.
Income (positive amounts) supplies the denominator; outflows are bucketed by
category; the residual (income minus all spending) is implicit savings.

The 50/30/20 guideline is a US default. In Switzerland, rent + Krankenkasse
premiums routinely push "needs" past 50 %. This function reports the user's
actual ratios neutrally — the LLM skill decides whether to comment.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import Transaction
from tools.categorize import categorize_transaction


@dataclass
class SplitResult:
    income_chf: float
    needs_chf: float
    wants_chf: float
    explicit_savings_chf: float   # money explicitly sent to savings/investments
    residual_savings_chf: float   # income − needs − wants − explicit_savings
    savings_chf: float            # explicit + residual (total saved)
    needs_pct: float              # share of income, 0–100
    wants_pct: float
    savings_pct: float


def compute_split(transactions: list[Transaction]) -> SplitResult:
    """Return needs/wants/savings ratios for the given transaction window.

    Uses txn.category when set (avoids redundant merchant lookups for
    already-categorised transactions); falls back to categorize_transaction
    for uncategorised outflows.

    Raises ValueError when there is no income in the transaction list —
    ratios cannot be computed without a denominator.
    """
    income = 0.0
    needs = 0.0
    wants = 0.0
    explicit_savings = 0.0

    for t in transactions:
        if t.amount > 0:
            income += t.amount
            continue

        cat = t.category if t.category is not None else categorize_transaction(t)
        abs_amount = abs(t.amount)

        if cat == "need":
            needs += abs_amount
        elif cat == "want":
            wants += abs_amount
        elif cat == "savings":
            explicit_savings += abs_amount

    if income == 0.0:
        raise ValueError(
            "No income transactions found; cannot compute split ratios. "
            "Ensure the transaction window contains at least one salary / deposit."
        )

    residual = income - needs - wants - explicit_savings
    total_savings = explicit_savings + max(0.0, residual)

    def pct(amount: float) -> float:
        return round(amount / income * 100, 1)

    return SplitResult(
        income_chf=round(income, 2),
        needs_chf=round(needs, 2),
        wants_chf=round(wants, 2),
        explicit_savings_chf=round(explicit_savings, 2),
        residual_savings_chf=round(residual, 2),
        savings_chf=round(total_savings, 2),
        needs_pct=pct(needs),
        wants_pct=pct(wants),
        savings_pct=pct(total_savings),
    )

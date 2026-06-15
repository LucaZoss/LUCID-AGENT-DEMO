"""
check_budget — deterministic rule the event loop calls on every new transaction.

Most transactions are silent (no breach). Only when a transaction pushes the
period total over the configured allocation does this return a BudgetBreach.

The caller is responsible for:
  • filtering period_transactions to the relevant calendar period
  • not passing the incoming txn itself inside period_transactions

check_budget never calls the LLM. If a breach is found, the diagnose_overspend
skill (Phase 3) converts it into a human sentence with an offered action.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import Budget, Transaction
from tools.categorize import categorize_transaction


@dataclass
class BudgetBreach:
    category: str           # 'need' | 'want' | 'savings'
    merchant: str
    txn_amount_chf: float   # absolute value of the triggering transaction
    period_spent_chf: float # total spent in this category after the transaction
    limit_chf: float
    overage_chf: float      # period_spent − limit
    overage_pct: float      # overage / limit * 100  (e.g. 15.0 = 15 % over)


def check_budget(
    txn: Transaction,
    budget: Budget,
    period_transactions: list[Transaction],
) -> BudgetBreach | None:
    """Return a BudgetBreach if *txn* pushes any category over its allocation.

    Returns None when:
      • txn is income (positive amount)
      • the budget has no allocation key for the transaction's category
      • the category total stays within the limit after adding txn

    Args:
        txn:                 the incoming transaction to check.
        budget:              the active Budget for the current period.
        period_transactions: already-settled transactions for the same period
                             (must NOT include txn itself).
    """
    if txn.amount >= 0:
        return None   # income — not a spending event

    category = txn.category if txn.category is not None else categorize_transaction(txn)

    limit = budget.allocations.get(category)
    if limit is None:
        return None   # no budget configured for this category

    already_spent = sum(
        abs(t.amount)
        for t in period_transactions
        if t.amount < 0
        and (t.category if t.category is not None else categorize_transaction(t)) == category
    )

    txn_abs = abs(txn.amount)
    total_after = already_spent + txn_abs

    if total_after <= limit:
        return None

    overage = total_after - limit
    return BudgetBreach(
        category=category,
        merchant=txn.merchant,
        txn_amount_chf=round(txn_abs, 2),
        period_spent_chf=round(total_after, 2),
        limit_chf=round(limit, 2),
        overage_chf=round(overage, 2),
        overage_pct=round(overage / limit * 100, 1),
    )

---
type: Tool
title: check_budget
description: Deterministic budget breach detection on each new transaction; returns BudgetBreach or None.
resource: tools/budget.py
tags: [tools, budgeting, notifications]
timestamp: 2026-06-26T12:00:00Z
---

# check_budget

## Source of truth

- [tools/budget.py](../../tools/budget.py)

## What it does

Event-loop rule called on every new transaction. Returns `BudgetBreach` when the transaction pushes a category over its allocation. Never calls the LLM — actionable breaches escalate to `diagnose_overspend` skill.

## API

```python
def check_budget(
    txn: Transaction,
    budget: Budget,
    period_transactions: list[Transaction],
) -> BudgetBreach | None:
```

## Caller responsibilities

- Filter `period_transactions` to the relevant calendar period.
- Do **not** include the incoming `txn` in `period_transactions`.

## Returns None when

- Transaction is income (positive amount)
- No allocation key for the transaction's category
- Category total stays within limit

## How to extend

- Breach shape is notification input — update [metrics/budget-breach.md](../metrics/budget-breach.md) and notification tier logic together.
- Category key must match `budget.allocations` keys.

## Related pages

- [metrics/budget-breach.md](../metrics/budget-breach.md)
- [skills/diagnose-overspend.md](../skills/diagnose-overspend.md)
- [contracts/budget.md](../contracts/budget.md)

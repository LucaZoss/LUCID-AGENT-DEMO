---
type: Metric
title: Budget Breach
description: BudgetBreach from check_budget when a transaction exceeds category allocation.
resource: tools/budget.py
tags: [metrics, budgeting, notifications]
timestamp: 2026-06-26T12:00:00Z
---

# Budget Breach

## Source of truth

- [tools/budget.py](../../tools/budget.py) — `BudgetBreach` dataclass, `check_budget()`

## What it does

Deterministic breach signal for the event loop. Triggers actionable notification tier and `diagnose_overspend` skill. Most transactions produce no breach (silent tier).

## BudgetBreach shape

| Field | Type | Description |
|-------|------|-------------|
| `category` | str | `need` \| `want` \| `savings` |
| `merchant` | str | Triggering merchant |
| `txn_amount_chf` | float | Absolute txn amount |
| `period_spent_chf` | float | Category total after txn |
| `limit_chf` | float | Budget allocation |
| `overage_chf` | float | period_spent − limit |
| `overage_pct` | float | overage / limit × 100 |

## Notification flow

```
check_budget → BudgetBreach → diagnose_overspend skill → pending_notifications
```

## Related pages

- [tools/check-budget.md](../tools/check-budget.md)
- [skills/diagnose-overspend.md](../skills/diagnose-overspend.md)
- [tables/conversation-and-prefs.md](../tables/conversation-and-prefs.md)

---
type: SQLite Table
title: budgets
description: Monthly category allocations and target needs/wants/savings ratios as JSON.
resource: db/db_schema.py
tags: [user-facts, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# budgets

## Source of truth

- [db/db_schema.py](../../db/db_schema.py)
- [contracts.py](../../contracts.py) — `Budget`
- [tools/budget.py](../../tools/budget.py) — `check_budget()`
- [skills/build_budget/SKILL.md](../../skills/build_budget/SKILL.md)

## What it does

Layer 1 durable user fact. Stores per-period CHF allocations per category and target NWS ratios. Used by `check_budget` for breach detection and dashboard budget-vs-actual.

## Key columns

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID |
| `user_id` | TEXT FK | → `users.id` |
| `allocations` | TEXT (JSON) | `{"groceries": 600, "dining": 200}` |
| `target_ratios` | TEXT (JSON) | `{"needs": 0.55, "wants": 0.25, "savings": 0.20}` |
| `period` | TEXT | e.g. `2026-06` (monthly) |
| `created_at` | TEXT | ISO timestamp |

## How to extend

- JSON shape is the contract — update [tools/dashboard.py](../../tools/dashboard.py) and frontend together if keys change.
- New budget period logic belongs in tools, not skills.

## Related pages

- [contracts/budget.md](../contracts/budget.md)
- [tools/check-budget.md](../tools/check-budget.md)
- [skills/build-budget.md](../skills/build-budget.md)

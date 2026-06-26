---
type: Dataclass
title: Budget
description: DTO for monthly category allocations and target needs/wants/savings ratios.
resource: contracts.py
tags: [contracts, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# Budget

## Source of truth

- [contracts.py](../../contracts.py) — `Budget` dataclass
- [tables/budgets.md](../tables/budgets.md)

## What it does

Represents a user's budget for one calendar period. `allocations` drives `check_budget`; `target_ratios` drives split comparison on dashboard.

## Fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | str | UUID |
| `user_id` | str | |
| `allocations` | dict[str, float] | Category → CHF cap |
| `target_ratios` | dict[str, float] | `needs`/`wants`/`savings` → 0–1 fraction |
| `period` | str | e.g. `2026-06` |

## How to extend

- JSON keys in DB must match dict keys here.
- Ratio changes are configurable — Swiss rent often pushes needs past 50%; never label as "wrong".

## Related pages

- [tables/budgets.md](../tables/budgets.md)
- [tools/check-budget.md](../tools/check-budget.md)
- [skills/build-budget.md](../skills/build-budget.md)

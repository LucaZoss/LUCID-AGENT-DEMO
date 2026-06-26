---
type: Metric
title: Dashboard Payload
description: Locked UI contract assembled by build_dashboard_payload for charts and progress views.
resource: tools/dashboard.py
tags: [metrics, dashboard, ui-contract]
timestamp: 2026-06-26T12:00:00Z
---

# Dashboard Payload

## Source of truth

- [tools/dashboard.py](../../tools/dashboard.py) — `DashboardPayload` and nested dataclasses

## What it does

Single contract between deterministic core and UI. All chart data flows through this shape. Lock early — frontend renders exactly these keys.

## DashboardPayload shape

| Field | Type | Description |
|-------|------|-------------|
| `period` | str | e.g. `2026-06` |
| `generated_at` | datetime | Snapshot timestamp |
| `split` | SplitResult | NWS composition |
| `top_merchants` | list[MerchantSummary] | Top 10 by spend |
| `category_breakdown` | list[CategoryLine] | need/want/savings lines |
| `budget_vs_actual` | list[BudgetVsActualLine] \| None | If budget supplied |
| `goal_progress` | dict \| None | If goal supplied |
| `income_chf` | float | |
| `total_outflow_chf` | float | |
| `net_chf` | float | income − outflow |
| `normalized_breakdown` | dict[str, float] \| None | Taxonomy key → CHF |

## Nested types

- `MerchantSummary` — merchant, total_chf, count, category
- `CategoryLine` — category, total_chf, pct_of_income
- `BudgetVsActualLine` — category, budget_chf, actual_chf, pct_used, over_budget

## How to extend

- Add/rename keys only with simultaneous frontend update.
- All math delegated to `compute_split` and `compute_goal_feasibility`.

## Related pages

- [tools/build-dashboard-payload.md](../tools/build-dashboard-payload.md)
- [metrics/needs-wants-savings-split.md](needs-wants-savings-split.md)
- [metrics/goal-feasibility.md](goal-feasibility.md)

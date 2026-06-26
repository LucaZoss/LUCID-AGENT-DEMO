---
type: Tool
title: build_dashboard_payload
description: Assembles locked DashboardPayload chart contract from transactions, budget, and goal.
resource: tools/dashboard.py
tags: [tools, dashboard, ui-contract]
timestamp: 2026-06-26T12:00:00Z
---

# build_dashboard_payload

## Source of truth

- [tools/dashboard.py](../../tools/dashboard.py)

## What it does

Assembles the full dashboard data contract. Lock this shape early — the UI renders exactly what is here. All monetary values in CHF; percentages are 0–100 floats.

## API

```python
def build_dashboard_payload(
    period: str,
    transactions: list[Transaction],
    budget: Budget | None = None,
    goal: StructuredGoal | None = None,
    current_savings: float = 0.0,
    monthly_income: float | None = None,
) -> DashboardPayload:
```

## DashboardPayload sections

| Section | Source |
|---------|--------|
| `split` | `compute_split()` |
| `top_merchants` | Top 10 by spend |
| `category_breakdown` | need/want/savings lines |
| `budget_vs_actual` | If budget supplied |
| `goal_progress` | If goal supplied |
| `normalized_breakdown` | By taxonomy key |

## How to extend

- Add/rename keys only with frontend contract update in the same PR.
- Delegates to `compute_split` and `compute_goal_feasibility` — no inline math.

## Related pages

- [metrics/dashboard-payload.md](../metrics/dashboard-payload.md)
- [tools/compute-split.md](compute-split.md)
- [tools/compute-goal-feasibility.md](compute-goal-feasibility.md)

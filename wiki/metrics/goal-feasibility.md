---
type: Metric
title: Goal Feasibility
description: FeasibilityResult — required monthly savings, on-track flag, months remaining.
resource: tools/feasibility.py
tags: [metrics, goals]
timestamp: 2026-06-26T12:00:00Z
---

# Goal Feasibility

## Source of truth

- [tools/feasibility.py](../../tools/feasibility.py) — `FeasibilityResult`, `compute_goal_feasibility()`

## What it does

Determines if a target goal is achievable by deadline given current savings pace and income. Open goals always return `on_track=True` with suggested 10% monthly rate.

## FeasibilityResult shape

| Field | Type | Description |
|-------|------|-------------|
| `goal_type` | str | `open` \| `target` |
| `required_monthly_chf` | float | CHF/month needed |
| `on_track` | bool | Pace sufficient? |
| `months_remaining` | float | For target goals |
| `still_needed_chf` | float | Gap to target |
| `suggested_rate_pct` | float | % of income |

## Dashboard usage

Embedded in `DashboardPayload.goal_progress` when goal is supplied to `build_dashboard_payload`.

## Related pages

- [tools/compute-goal-feasibility.md](../tools/compute-goal-feasibility.md)
- [contracts/structured-goal.md](../contracts/structured-goal.md)
- [metrics/dashboard-payload.md](dashboard-payload.md)

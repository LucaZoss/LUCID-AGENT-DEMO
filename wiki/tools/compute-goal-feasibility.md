---
type: Tool
title: compute_goal_feasibility
description: Date arithmetic for required monthly savings and on-track flag; no LLM.
resource: tools/feasibility.py
tags: [tools, goals, metrics]
timestamp: 2026-06-26T12:00:00Z
---

# compute_goal_feasibility

## Source of truth

- [tools/feasibility.py](../../tools/feasibility.py)

## What it does

Answers whether the user can hit a savings target by deadline. Open goals get a suggested 10% pay-yourself-first rate and are always `on_track`. Target goals compute `required_monthly_chf` from remaining amount and months left.

## API

```python
def compute_goal_feasibility(
    goal: StructuredGoal,
    monthly_income: float,
    current_savings: float,
    reference_date: date | None = None,
) -> FeasibilityResult:
```

## FeasibilityResult fields

| Field | Description |
|-------|-------------|
| `required_monthly_chf` | CHF/month needed |
| `on_track` | Whether current pace suffices |
| `months_remaining` | For target goals |
| `still_needed_chf` | Target minus current savings |
| `suggested_rate_pct` | required_monthly / income × 100 |

## How to extend

- Raises `ValueError` on zero income or incomplete target goals.
- `reference_date` parameter exists for testability.
- Tests in `tests/test_tools.py` or dedicated feasibility tests.

## Related pages

- [metrics/goal-feasibility.md](../metrics/goal-feasibility.md)
- [contracts/structured-goal.md](../contracts/structured-goal.md)
- [tools/build-dashboard-payload.md](build-dashboard-payload.md)

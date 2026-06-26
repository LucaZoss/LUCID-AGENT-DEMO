---
type: Dataclass
title: StructuredGoal
description: DTO for user financial goals — open or target with engagement and framework.
resource: contracts.py
tags: [contracts, goals, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# StructuredGoal

## Source of truth

- [contracts.py](../../contracts.py) — `StructuredGoal` dataclass
- [tables/goals.md](../tables/goals.md)

## What it does

Authoritative shape for user goals after `goal_intake`. Drives framework selection and `compute_goal_feasibility`.

## Fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | str | UUID |
| `user_id` | str | |
| `goal_type` | str | `open` \| `target` |
| `engagement` | str | `low` \| `high` |
| `amount` | float \| None | Null for open goals |
| `target_date` | date \| None | Null for open goals |
| `framework` | str \| None | `50_30_20` \| `zero_based` \| `pay_first` |
| `active` | bool | Default `True` |

## How to extend

- Persist from skill JSON block (`goal_intake_result`) via deterministic write — not LLM free text.
- Open goals must not have invented `amount` values.

## Related pages

- [tables/goals.md](../tables/goals.md)
- [skills/goal-intake.md](../skills/goal-intake.md)
- [metrics/goal-feasibility.md](../metrics/goal-feasibility.md)

---
type: SQLite Table
title: goals
description: Structured financial goals — open-ended or specific target with amount and date.
resource: db/db_schema.py
tags: [user-facts, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# goals

## Source of truth

- [db/db_schema.py](../../db/db_schema.py)
- [contracts.py](../../contracts.py) — `StructuredGoal`
- [skills/goal_intake/SKILL.md](../../skills/goal_intake/SKILL.md) — intake procedure

## What it does

Layer 1 durable user fact. Output of `goal_intake` skill. Drives framework routing and feasibility calculations. Only one active goal per user in typical flows.

## Key columns

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID |
| `user_id` | TEXT FK | → `users.id` |
| `goal_type` | TEXT | `open` \| `target` |
| `amount` | REAL | Null for open goals |
| `target_date` | TEXT | ISO date; null for open goals |
| `engagement` | TEXT | `low` \| `high` — routes framework |
| `framework` | TEXT | `50_30_20` \| `zero_based` \| `pay_first` |
| `active` | INTEGER | 1 = current goal |

## Framework routing

| User goal | Framework |
|-----------|-----------|
| Open-ended ("save money") | Pay-yourself-first or 50/30/20 |
| Specific target + date | Zero-based |
| Wants control / will track | Zero-based |
| Wants minimal effort | Pay-yourself-first |

Never invent a target amount for open-ended goals.

## How to extend

- Persist via deterministic tool after LLM collects JSON from skill — not free-form chat parsing.
- Update [contracts/structured-goal.md](../contracts/structured-goal.md) if fields change.

## Related pages

- [contracts/structured-goal.md](../contracts/structured-goal.md)
- [skills/goal-intake.md](../skills/goal-intake.md)
- [metrics/goal-feasibility.md](../metrics/goal-feasibility.md)

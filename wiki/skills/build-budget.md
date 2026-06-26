---
type: Skill
title: build_budget
description: Build CHF category allocations grounded in transaction history for the chosen framework.
resource: skills/build_budget/SKILL.md
tags: [skills, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# build_budget

## Source of truth

- [skills/build_budget/SKILL.md](../../skills/build_budget/SKILL.md)

## What it does

Produces concrete monthly CHF allocations and target ratios for the user's framework. Calls categorization and split tools on real data. Output is persisted to `budgets` table and fed to dashboard.

## Typical tool chain

```
get_transactions → categorize → compute_split → build allocations
```

## Rules for coding agents

- Allocations must be grounded in computed numbers, not LLM estimates.
- Swiss needs often exceed 50% — report neutrally.
- After budget built, call `build_dashboard_payload` for dashboard render.

## Related pages

- [contracts/budget.md](../contracts/budget.md)
- [tables/budgets.md](../tables/budgets.md)
- [tools/build-dashboard-payload.md](../tools/build-dashboard-payload.md)

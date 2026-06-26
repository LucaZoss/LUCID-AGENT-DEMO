---
type: Skill
title: diagnose_overspend
description: Turn BudgetBreach into one human sentence with a concrete offered action for actionable notifications.
resource: skills/diagnose_overspend/SKILL.md
tags: [skills, notifications, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# diagnose_overspend

## Source of truth

- [skills/diagnose_overspend/SKILL.md](../../skills/diagnose_overspend/SKILL.md)

## What it does

Escalation skill for actionable notification tier. Called after `check_budget` returns a `BudgetBreach`. Produces one human-readable sentence plus offered action (e.g. pull from buffer, tighten next week). Renders as Telegram inline buttons in production.

## Input

`BudgetBreach` from [tools/check_budget](../../tools/budget.py) — deterministic, already computed.

## Rules for coding agents

- Never notify about something the user can't act on.
- Frequency cap (max 2–3 actionable pushes/day) and quiet hours are config in `prefs`, not this skill.
- Store pending notification in `pending_notifications` with `offered_actions` JSON.

## Related pages

- [metrics/budget-breach.md](../metrics/budget-breach.md)
- [tools/check-budget.md](../tools/check-budget.md)
- [tables/conversation-and-prefs.md](../tables/conversation-and-prefs.md)

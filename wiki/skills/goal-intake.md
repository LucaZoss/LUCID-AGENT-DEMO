---
type: Skill
title: goal_intake
description: Collect structured goal, engagement appetite, and monthly income; never name frameworks to user.
resource: skills/goal_intake/SKILL.md
tags: [skills, goals, onboarding]
timestamp: 2026-06-26T12:00:00Z
---

# goal_intake

## Source of truth

- [skills/goal_intake/SKILL.md](../../skills/goal_intake/SKILL.md)

## What it does

First skill in the budgeting conversation flow. Collects goal type (open vs target), engagement level, and monthly income. Outputs a JSON block tagged `goal_intake_result` for deterministic persistence.

## Frontmatter

| Field | Value |
|-------|-------|
| `tools_required` | `[]` |
| `outputs` | `structured_goal` |

## Output JSON shape

```json
{
  "goal_type": "open" | "target",
  "amount": null | <number>,
  "target_date": null | "YYYY-MM-DD",
  "engagement": "low" | "high",
  "monthly_income_chf": <number>
}
```

## Rules for coding agents

- Never invent savings target for open-ended goals.
- LLM stores numbers only — feasibility math is downstream in tools.
- Hand off to `recommend_framework` after confirmation.

## Related pages

- [contracts/structured-goal.md](../contracts/structured-goal.md)
- [skills/recommend-framework.md](recommend-framework.md)
- [conventions/adding-a-skill.md](../conventions/adding-a-skill.md)

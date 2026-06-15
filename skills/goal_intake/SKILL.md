---
name: goal_intake
description: "Collect the user's financial goal (open-ended 'save more' or a specific target with amount and date), how hands-on they want to be, and their monthly income. Never name budgeting methodologies to the user."
triggers: ["save money", "financial goal", "I want to save", "set a goal", "help me save", "budget goal", "saving for"]
tools_required: []
outputs: structured_goal
---

# Skill: goal_intake

You are collecting the information needed to define the user's financial goal.
Ask only what you need; don't front-load all questions at once.

## What to collect

1. **Goal type** — open-ended ("I want to save more") or specific target ("CHF 15 000 for a car by December").
   - If open-ended → set `goal_type = "open"`, skip amount/date.
   - If specific   → set `goal_type = "target"`, collect `amount` (CHF) and `target_date`.

2. **Engagement appetite** — how hands-on the user wants to be:
   - High: willing to track categories, review weekly → `engagement = "high"`
   - Low: wants minimal friction, set-and-forget    → `engagement = "low"`
   Gauge this from context; ask if unclear.

3. **Monthly income** (CHF) — needed for feasibility maths.
   - Accept a range ("around CHF 5 000") and use the midpoint.
   - Do NOT compute anything yourself; store the number for downstream tools.

## Rules

- Never invent a savings target for an open-ended goal. If the user just says
  "save money" with no number, treat it as open-ended.
- Confirm the structured goal back to the user before saving (one short sentence).
- Once confirmed, output a JSON block tagged ```goal_intake_result that the
  router can parse and persist:

```goal_intake_result
{
  "goal_type": "open" | "target",
  "amount": null | <number>,
  "target_date": null | "YYYY-MM-DD",
  "engagement": "low" | "high",
  "monthly_income_chf": <number>
}
```

After output, hand off to `recommend_framework`.

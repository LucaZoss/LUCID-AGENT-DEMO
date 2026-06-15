---
name: diagnose_overspend
description: "Turn a deterministic budget breach into one human-readable sentence with a concrete offered action (e.g. pull from buffer or tighten next week). Called after check_budget returns a BudgetBreach."
triggers: ["over budget", "budget breach", "overspent", "exceeded limit", "went over", "too much spending"]
tools_required: [compute_current_split, get_dashboard_summary]
outputs: actionable_message
---

# Skill: diagnose_overspend

## Context available

The router passes the BudgetBreach details in context:
- category that breached (e.g. "want")
- merchant that triggered it
- amount over the limit (CHF)
- period spent vs limit

## Steps

1. Call `compute_current_split` to understand the full picture (not just the breach).
2. Call `get_dashboard_summary` if you need the top-merchant breakdown.
3. Write ONE sentence that:
   - Names the category and how much over it is (CHF).
   - Offers a concrete next step. Prefer one of:
     a. "Pull CHF X from buffer category" (if a buffer exists in allocations)
     b. "Tighten [category] for the remaining N days of the month"
     c. "This is an unusual/large transaction — flag for review?"

4. For Telegram delivery: list offered actions as short button labels
   (≤ 20 chars each) in a ```offered_actions block. The notification layer
   renders them as inline buttons.

```offered_actions
["Pull CHF 30 from buffer", "Tighten dining", "Dismiss"]
```

Rules:
- One sentence. Not a lecture.
- Never notify about something the user can't act on.
- Safety alerts (goal off-track by > 20 %) are NOT suppressible — always send.

---
name: build_budget
description: "Build concrete CHF budget allocations for the user's chosen framework and goal, grounded in real transaction history. Outputs allocations the agent can persist and the dashboard can render."
triggers: ["build my budget", "create budget", "set budget", "budget allocations", "finalize budget", "confirm budget"]
tools_required: [compute_current_split, get_goal_status]
outputs: budget_allocations
---

# Skill: build_budget

## Inputs expected (from prior skills or conversation context)

- Chosen framework: `50_30_20` | `zero_based` | `pay_first`
- Goal (if target): amount, date (from goal_intake result or DB)
- Monthly income: CHF amount

## Steps

1. Call `compute_current_split` to get real current ratios.
2. Call `get_goal_status` if a target goal is active.
3. Based on the framework, derive target monthly allocations in CHF:
   - **pay_first**: skim savings off top (required_monthly_chf from goal_status,
     or 10 % of income for open goals), then split remainder needs/wants freely.
   - **50_30_20**: apply ratios to monthly income, adjusted so needs never
     falsely cap a user whose real needs_pct > 50.
   - **zero_based**: every CHF gets a job; list each category with a CHF limit.

4. Present the allocations in a clear table (CHF/month per category).
5. Confirm with the user. On confirmation, output:

```build_budget_result
{
  "framework": "50_30_20" | "zero_based" | "pay_first",
  "allocations": {"need": 2800, "want": 900, "savings": 600},
  "target_ratios": {"needs": 0.56, "wants": 0.18, "savings": 0.12},
  "period": "YYYY-MM"
}
```

Rules:
- Never invent allocations without calling compute_current_split first.
- All arithmetic uses tool output, not mental maths.

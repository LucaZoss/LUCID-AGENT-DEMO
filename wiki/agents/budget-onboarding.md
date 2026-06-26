---
type: Agent
title: Budget Onboarding
description: Deterministic post-import HITL — income ID, needs classification, auto-classify remainder; no LLM.
resource: agents/budget_onboarding/agent.py
tags: [agents, onboarding, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# Budget Onboarding

## Source of truth

- [agents/budget_onboarding/agent.py](../../agents/budget_onboarding/agent.py) — `run_budget_onboarding()`
- [agents/budget_onboarding/tools.py](../../agents/budget_onboarding/tools.py)

## What it does

Final pre-REPL stage in CSV pipeline. **Deterministic HITL with no LLM.** Identifies income accounts, computes net balance, classifies essentials as needs, auto-classifies remainder into need/want/savings buckets.

## Tools

`fetch_income_candidates`, `apply_category_by_line_categories`, etc.

## How to extend

- Keep this agent LLM-free — use deterministic rules and REPL prompts.
- Writes directly to `transactions.category` and related fields.

## Related pages

- [architecture/startup-pipeline.md](../architecture/startup-pipeline.md)
- [agents/labeller-agent.md](labeller-agent.md)
- [tools/categorize-transaction.md](../tools/categorize-transaction.md)

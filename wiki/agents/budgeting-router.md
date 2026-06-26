---
type: Agent
title: Budgeting Router
description: Main orchestrator loop — route to skill, assemble context, tool-calling loop, persist turn.
resource: orchestrator/router.py
tags: [agents, router, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# Budgeting Router

## Source of truth

- [orchestrator/router.py](../../orchestrator/router.py) — `route()`, `handle_message()`
- [orchestrator/context_assembler.py](../../orchestrator/context_assembler.py)
- [llm/tool_definitions.py](../../llm/tool_definitions.py)

## What it does

Main budgeting agent loop. Two-stage skill loading: `list_skills()` manifest → router picks skill → `read_skill()` full load → tool-calling loop → persist conversation turn.

## Flow

```
user message
  → list_skills() (cheap manifest)
  → router LLM picks skill(s)
  → read_skill(name) (full SKILL.md)
  → assemble_context() (DB + fresh tools)
  → tool-calling loop
  → response + DB persist
```

## Wires Phase-2 tools

`compute_split`, `check_budget`, `compute_goal_feasibility`, `build_dashboard_payload`, `categorize_transaction`

## Rules for coding agents

- Do **not** route ledger categorization through this loop.
- Do **not** add LLM arithmetic — delegate to tools.
- REPL (`repl.py`) is presentation only — logic stays here.

## Related pages

- [architecture/layer-rules.md](../architecture/layer-rules.md)
- [conventions/adding-a-skill.md](../conventions/adding-a-skill.md)
- [agents/ledger-categorizer.md](ledger-categorizer.md)

---
type: Architecture
title: Startup Pipeline
description: Staged startup — model selection, data source, ETL, labeller, rules, onboarding, REPL.
resource: orchestrator/startup.py
tags: [architecture, startup, etl]
timestamp: 2026-06-26T12:00:00Z
---

# Startup Pipeline

## Source of truth

- [orchestrator/startup.py](../../orchestrator/startup.py) — `run_startup()`, `StartupStage`
- [orchestrator/repl.py](../../orchestrator/repl.py) — invokes startup before REPL loop

## What it does

On launch, the REPL runs a staged startup state machine before accepting chat messages. The CSV import path chains multiple agents in a fixed order; the demo bank path skips ETL.

## Stages

| Stage | What happens |
|-------|--------------|
| Model | Detect/select LLM provider via `llm/config.py` |
| Data source | Demo bank seed vs CSV import (`LUCID_LEDGER`) |
| Persistence | Optional file DB (`LUCID_DB_PATH`) |
| ETL loader | `agents/etl_loader` — scan CSVs, mapping HITL, import |
| Labeller | `agents/labeller` — `clean_name`, `line_category` on outflows |
| Rules review | `agents/labeller/rules_flow` — merchant pattern rules |
| Budget onboarding | `agents/budget_onboarding` — deterministic needs classification |
| REPL | Interactive chat via `orchestrator/router.py` |

## CSV path order

```
ETL Loader → Labeller → Rules Review → Budget Onboarding → REPL
```

Each agent writes to SQLite; the next stage reads unprocessed rows.

## Demo path

When `LUCID_LEDGER=demo` (default), `SimulatedBank` seeds transactions. ETL/labeller/onboarding stages are skipped or abbreviated.

## How to extend

- New startup stage → add `StartupStage` enum value + handler in `startup.py`; do not block REPL on LLM unless necessary.
- New pre-REPL agent → insert in pipeline order; document in this page.
- Keep startup **presentation** in `repl.py` thin — logic stays in `startup.py`.

## Related pages

- [agents/etl-loader-agent.md](../agents/etl-loader-agent.md)
- [agents/labeller-agent.md](../agents/labeller-agent.md)
- [agents/budget-onboarding.md](../agents/budget-onboarding.md)
- [cli/environment-variables.md](../cli/environment-variables.md)

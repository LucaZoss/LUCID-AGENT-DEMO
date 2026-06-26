---
type: CLI
title: REPL Slash Commands
description: Terminal REPL slash commands for import, mapping profiles, and ledger categorization HIL.
resource: orchestrator/repl.py
tags: [cli, repl, commands]
timestamp: 2026-06-26T12:00:00Z
---

# REPL Slash Commands

## Source of truth

- [orchestrator/repl.py](../../orchestrator/repl.py) — `main()`, slash command handlers
- [REPL_README.md](../../REPL_README.md) — user-facing setup guide

## What it does

Rich TUI REPL entry point (`uv run lucid-agent`). Slash commands handle import and categorization HIL. Chat messages delegate to `router.handle_message()`.

## Import commands

| Command | Action |
|---------|--------|
| `/setup` | Checklist: import folder, `LUCID_DB_PATH`, categorization commands |
| `/import` | Import all `*.csv` in import directory |
| `/import preview <file>` | Headers, mapping, sample rows |
| `/import-preview <file>` | Alias for above |
| `/import-rollback <batch_id>` | Delete transactions from one batch |
| `/import-mapping list` | List saved mapping profiles |
| `/import-mapping save <name>` | Save mapping from last preview |
| `/import-mapping set-default <id>` | Mark profile as default |

## Categorization commands

| Command | Action |
|---------|--------|
| `/cat-run` | Run ledger categorization LLM (separate from budgeting agent) |
| `/review-categories` | List pending proposals + deterministic hint |
| `/cat-accept <id> [bucket] [line]` | Apply proposal with optional overrides |
| `/cat-reject <id>` | Reject proposal |

## Rules for coding agents

- REPL is **presentation only** — business logic in `ingest/`, `agents/`, `router.py`.
- New slash commands → handler in `repl.py` + document here and in REPL_README.

## Related pages

- [cli/environment-variables.md](environment-variables.md)
- [agents/ledger-categorizer.md](../agents/ledger-categorizer.md)
- [datasets/csv-import.md](../datasets/csv-import.md)

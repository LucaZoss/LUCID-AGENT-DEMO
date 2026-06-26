---
type: Agent
title: Ledger Categorizer
description: Separate LLM loop for normalized taxonomy proposals; HIL commit via REPL /cat-accept.
resource: agents/ledger_categorizer.py
tags: [agents, ledger, categorization]
timestamp: 2026-06-26T12:00:00Z
---

# Ledger Categorizer

## Source of truth

- [agents/ledger_categorizer.py](../../agents/ledger_categorizer.py) — `run_ledger_categorizer()`
- [agents/ledger_tools.py](../../agents/ledger_tools.py)
- [docs/IMPORT_AND_LEDGER_CATEGORIZATION.md](../../docs/IMPORT_AND_LEDGER_CATEGORIZATION.md)

## What it does

**Second small LLM loop** — separate from budgeting router. Classifies transactions into normalized taxonomy via `propose_normalized_category`. Proposals land in `category_proposals` until user applies via `/cat-accept`.

## Tools

`propose_spending_bucket`, `propose_line_category`, `propose_normalized_category`, `apply_proposal`

## Rules for coding agents

- Does **not** use `orchestrator/router.py` or budgeting skills.
- Proposals only in agent loop — `apply_proposal` called from REPL HIL.
- Taxonomy keys must be in [categories.py](../../categories.py).

## REPL commands

`/cat-run`, `/review-categories`, `/cat-accept`, `/cat-reject`

## Related pages

- [tables/categorization.md](../tables/categorization.md)
- [datasets/category-taxonomy.md](../datasets/category-taxonomy.md)
- [cli/repl-slash-commands.md](../cli/repl-slash-commands.md)

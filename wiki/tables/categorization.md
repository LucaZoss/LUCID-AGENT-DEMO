---
type: SQLite Table
title: Categorization
description: Category proposals (HIL pending) and merchant override memory for labeller and ledger agent.
resource: db/db_schema.py
tags: [categorization, hil, ledger]
timestamp: 2026-06-26T12:00:00Z
---

# Categorization

## Source of truth

- [db/db_schema.py](../../db/db_schema.py) — `category_proposals`, `merchant_category_overrides`
- [agents/ledger_categorizer.py](../../agents/ledger_categorizer.py)
- [agents/ledger_tools.py](../../agents/ledger_tools.py)
- [docs/IMPORT_AND_LEDGER_CATEGORIZATION.md](../../docs/IMPORT_AND_LEDGER_CATEGORIZATION.md)

## What it does

Two tables support human-in-the-loop categorization. Proposals are **not** applied until user accepts via REPL `/cat-accept`. Merchant overrides are durable memory for auto-apply on future imports.

## category_proposals

| Column | Notes |
|--------|-------|
| `txn_id` | FK → `transactions.id` |
| `proposed_bucket` | Legacy: `need` \| `want` \| `savings` |
| `proposed_line` | Legacy fine label |
| `proposed_normalized` | Canonical taxonomy key |
| `rationale` | Agent explanation |
| `status` | `pending` \| `accepted` \| `rejected` |

## merchant_category_overrides

| Column | Notes |
|--------|-------|
| `merchant_normalized` | Pattern matched against raw merchant |
| `canonical_name` | Clean display name |
| `normalized_category` | Canonical taxonomy key |
| `source` | `user_confirmed` \| `sector_rule` \| `llm_proposed` |
| `confidence` | 0.0–1.0 |
| `override_count` | Times user manually changed suggestion |

Unique on `(user_id, merchant_normalized)`.

## How to extend

- Ledger agent proposes only — `apply_proposal` in ledger_tools commits.
- Never auto-accept proposals in agent loop without explicit HIL.
- Taxonomy keys must exist in [categories.py](../../categories.py).

## Related pages

- [agents/ledger-categorizer.md](../agents/ledger-categorizer.md)
- [datasets/category-taxonomy.md](../datasets/category-taxonomy.md)
- [cli/repl-slash-commands.md](../cli/repl-slash-commands.md)

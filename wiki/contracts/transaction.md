---
type: Dataclass
title: Transaction
description: DTO for bank movements crossing bank, tools, LLM, and dashboard layers.
resource: contracts.py
tags: [contracts, ledger]
timestamp: 2026-06-26T12:00:00Z
---

# Transaction

## Source of truth

- [contracts.py](../../contracts.py) — `Transaction` dataclass
- [tables/transactions.md](../tables/transactions.md) — DB mirror

## What it does

Stable data-transfer object for a single bank movement. Keep shape stable — downstream tools, DB mappers, and dashboard depend on it.

## Fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | str | UUID |
| `account_id` | str | |
| `amount` | float | Negative = outflow, CHF |
| `currency` | str | `'CHF'` in demo |
| `merchant` | str | Raw merchant string |
| `category` | str \| None | Legacy: `need` \| `want` \| `savings` |
| `ts` | datetime | |
| `line_category` | str \| None | Fine label |
| `normalized_category` | str \| None | Taxonomy key |
| `import_batch_id` | str \| None | |
| `external_fingerprint` | str \| None | CSV dedupe |

**DB-only gap:** `clean_name` exists in SQLite but is not yet on this dataclass. Sync when extending.

## How to extend

- Add field → update `contracts.py`, `db/queries.py`, `bank/db_provider.py`, and schema together.
- Do not add computed fields to the dataclass — compute in tools.

## Related pages

- [tables/transactions.md](../tables/transactions.md)
- [tools/categorize-transaction.md](../tools/categorize-transaction.md)
- [datasets/category-taxonomy.md](../datasets/category-taxonomy.md)

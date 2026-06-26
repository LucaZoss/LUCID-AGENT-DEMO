---
type: SQLite Table
title: transactions
description: One row per bank movement; authoritative ledger for all spending and income.
resource: db/db_schema.py
tags: [ledger, csv-import, categorization]
timestamp: 2026-06-26T12:00:00Z
---

# transactions

## Source of truth

- [db/db_schema.py](../../db/db_schema.py) — `CREATE TABLE transactions`
- [contracts.py](../../contracts.py) — `Transaction` dataclass (partial mirror)
- [db/queries.py](../../db/queries.py) — `_row_to_txn()`
- [bank/db_provider.py](../../bank/db_provider.py) — reads for `BankingProvider`

## What it does

Core ledger table. Every outflow and inflow lands here — from simulated bank seed, CSV import, or future SIX sync. Negative `amount` = outflow (CHF).

## Key columns

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID |
| `account_id` | TEXT FK | → `accounts.id` |
| `amount` | REAL | Negative = outflow |
| `currency` | TEXT | Default `CHF` |
| `merchant` | TEXT | Raw merchant string from bank/CSV |
| `clean_name` | TEXT | Normalized name from Labeller agent |
| `category` | TEXT | Legacy bucket: `need` \| `want` \| `savings` |
| `line_category` | TEXT | Fine label: `rent`, `groceries`, etc. |
| `normalized_category` | TEXT | Canonical key from `categories.py` |
| `ts` | TEXT | ISO timestamp |
| `import_batch_id` | TEXT FK | → `import_batches.id` (null for demo seed) |
| `external_fingerprint` | TEXT | Dedupe key; unique per account when set |

## Indexes

- `idx_txn_account_ts` — `(account_id, ts)`
- `idx_txn_fingerprint` — partial unique on `(account_id, external_fingerprint)` where not null

## How to extend

- New column → [conventions/adding-a-db-column.md](../conventions/adding-a-db-column.md).
- Update `Transaction` dataclass and all row mappers together.
- Categorization writes go through agents or REPL `/cat-accept`, not ad-hoc SQL in router.

## Related pages

- [contracts/transaction.md](../contracts/transaction.md)
- [tables/accounts.md](accounts.md)
- [tables/import-and-profiles.md](import-and-profiles.md)
- [datasets/category-taxonomy.md](../datasets/category-taxonomy.md)

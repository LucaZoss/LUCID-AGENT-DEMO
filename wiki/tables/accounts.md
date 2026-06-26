---
type: SQLite Table
title: accounts
description: User bank accounts with balance, currency, type, and income flag.
resource: db/db_schema.py
tags: [ledger, multi-account]
timestamp: 2026-06-26T12:00:00Z
---

# accounts

## Source of truth

- [db/db_schema.py](../../db/db_schema.py)
- [contracts.py](../../contracts.py) — `Account` dataclass
- [ingest/account_detect.py](../../ingest/account_detect.py) — heuristic account type detection

## What it does

Stores one row per linked bank account. Balance is reconciled from transaction sums during CSV import. `has_income` flags accounts that receive salary.

## Key columns

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID |
| `user_id` | TEXT FK | → `users.id` |
| `name` | TEXT | Display name |
| `balance` | REAL | Current balance CHF |
| `currency` | TEXT | Default `CHF` |
| `account_type` | TEXT | `checking` \| `credit_card` \| `savings` |
| `has_income` | INTEGER | 1 = regular income present |

## How to extend

- `account_type` and `has_income` were added via `migrate_schema()` — follow same pattern for new columns.
- Multi-account CSV import uses [ingest/accounts.py](../../ingest/accounts.py).

## Related pages

- [contracts/account.md](../contracts/account.md)
- [tables/transactions.md](transactions.md)
- [datasets/csv-import.md](../datasets/csv-import.md)

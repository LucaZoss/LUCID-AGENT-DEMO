---
type: Dataclass
title: Account
description: DTO for a user bank account with balance, type, and income flag.
resource: contracts.py
tags: [contracts, ledger]
timestamp: 2026-06-26T12:00:00Z
---

# Account

## Source of truth

- [contracts.py](../../contracts.py) — `Account` dataclass
- [tables/accounts.md](../tables/accounts.md)

## What it does

Represents a linked bank account. Used by `BankingProvider` implementations and budget onboarding for income detection.

## Fields

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id` | str | | UUID |
| `user_id` | str | | |
| `name` | str | | Display name |
| `balance` | float | | CHF |
| `currency` | str | `"CHF"` | |
| `account_type` | str | `"checking"` | `checking` \| `credit_card` \| `savings` |
| `has_income` | bool | `False` | Salary account flag |

## How to extend

- New account metadata → add to dataclass + `accounts` table + mappers in `bank/db_provider.py`.

## Related pages

- [tables/accounts.md](../tables/accounts.md)
- [agents/budget-onboarding.md](../agents/budget-onboarding.md)

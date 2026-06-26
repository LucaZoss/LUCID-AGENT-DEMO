---
type: Dataset
title: Category Taxonomy
description: Canonical normalized category keys in categories.py — single source of truth for classification.
resource: categories.py
tags: [dataset, taxonomy, categorization]
timestamp: 2026-06-26T12:00:00Z
---

# Category Taxonomy

## Source of truth

- [categories.py](../../categories.py) — `TAXONOMY`, `BY_KEY`, `VALID_KEYS`
- [categories_mapping.py](../../categories_mapping.py) — line category → taxonomy key

## What it does

Single source of truth for `normalized_category` column values. Never hard-code category strings elsewhere — import from `categories.py`.

## NormalizedCategory shape

| Field | Example | Notes |
|-------|---------|-------|
| `key` | `groceries_food` | DB slug |
| `name` | Groceries/Food | Display label |
| `group` | Needs | Needs \| Wants \| Income \| Extras |
| `top_type` | Expenses | Expenses \| Income \| Extras |

## Legacy bucket mapping

`derive_legacy_bucket(key)` maps taxonomy to need/want/savings:

| Group | Bucket |
|-------|--------|
| Needs | `need` |
| Wants | `want` |
| Income, Extras | `None` (excluded from NWS split) |

## Key categories

**Needs:** rent, health_insurance, groceries_food, telecom

**Wants:** car, clothing, restaurants, transport, travel_holidays, wants_other

**Income:** salary

**Extras:** twint_credit, twint_debit, extras_other

## How to extend

1. Add `NormalizedCategory` to `TAXONOMY` in `categories.py`.
2. Update `categories_mapping.py` if line labels map to it.
3. Add test in `tests/test_categories.py`.
4. Ledger categorizer proposals must use valid `VALID_KEYS`.

## Related pages

- [tables/categorization.md](../tables/categorization.md)
- [agents/ledger-categorizer.md](../agents/ledger-categorizer.md)
- [contracts/transaction.md](../contracts/transaction.md)

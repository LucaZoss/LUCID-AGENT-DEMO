---
type: Tool
title: ETL and Labeller Tools
description: Column mapping, complexity analysis, normalization, merchant cleaning, and bucket classification helpers.
resource: tools/etl/
tags: [tools, etl, labeller]
timestamp: 2026-06-26T12:00:00Z
---

# ETL and Labeller Tools

## Source of truth

### ETL (`tools/etl/`)

| Module | Functions | Purpose |
|--------|-----------|---------|
| [column_mapper.py](../../tools/etl/column_mapper.py) | `header_fingerprint`, `heuristic_map` | Stable header hash; auto-detect CSV columns |
| [complexity_analyzer.py](../../tools/etl/complexity_analyzer.py) | `analyze_complexity` | Choose pandas vs html parse strategy |
| [normalizer.py](../../tools/etl/normalizer.py) | `normalize_dataframe` | Rows → canonical date/merchant/amount/currency |

### Labeller (`tools/labeller/`)

| Module | Functions | Purpose |
|--------|-----------|---------|
| [name_cleaner.py](../../tools/labeller/name_cleaner.py) | `clean_merchant_name` | Strip locations, title-case |
| [bucket_classifier.py](../../tools/labeller/bucket_classifier.py) | `classify_bucket` | Wraps `categorize_transaction` + sector hint |

## What it does

Supporting deterministic tools for the ETL loader and labeller agents. Not part of the core budgeting router API exported from `tools/__init__.py`.

## How to extend

- ETL changes → update [agents/etl_loader/tools.py](../../agents/etl_loader/tools.py) bindings.
- Labeller changes → update [agents/labeller/tools.py](../../agents/labeller/tools.py).
- Swiss/English header synonyms belong in `column_mapper.py` heuristics.

## Related pages

- [agents/etl-loader-agent.md](../agents/etl-loader-agent.md)
- [agents/labeller-agent.md](../agents/labeller-agent.md)
- [datasets/csv-import.md](../datasets/csv-import.md)

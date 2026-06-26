---
type: Tool
title: categorize_transaction
description: Rule-based merchant substring matching to need, want, or savings bucket.
resource: tools/categorize.py
tags: [tools, categorization]
timestamp: 2026-06-26T12:00:00Z
---

# categorize_transaction

## Source of truth

- [tools/categorize.py](../../tools/categorize.py)

## What it does

Deterministic spending classifier. First substring match wins (case-insensitive). Priority: savings → want → need. No LLM fallback in this module — ambiguous merchants default conservatively to `want`.

## API

```python
def categorize_transaction(txn: Transaction) -> str:
    """Returns 'need' | 'want' | 'savings'."""
```

## Rules

- More-specific patterns listed before broader ones (e.g. `"to go"` before `"coop"`).
- Uses `txn.category` when already set on the transaction.
- Swiss merchants heavily represented in `_RULES` table.

## How to extend

- Add `(substring, category)` tuples to `_RULES` in priority order.
- Add test cases in `tests/test_tools.py` for new merchants.
- For taxonomy-level classification, use ledger categorizer + `categories.py`.

## Related pages

- [tools/etl-and-labeller.md](etl-and-labeller.md)
- [datasets/category-taxonomy.md](../datasets/category-taxonomy.md)
- [conventions/adding-a-tool.md](../conventions/adding-a-tool.md)

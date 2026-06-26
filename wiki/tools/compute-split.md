---
type: Tool
title: compute_split
description: Pure math needs/wants/savings ratios from transaction list; returns SplitResult.
resource: tools/split.py
tags: [tools, metrics, split]
timestamp: 2026-06-26T12:00:00Z
---

# compute_split

## Source of truth

- [tools/split.py](../../tools/split.py)

## What it does

Computes needs/wants/savings split from transactions. Income (positive amounts) is the denominator in `income_based` mode. Falls back to `spend_composition` when no income is present (credit-card-only imports). Reports actual ratios neutrally — never calls them "wrong" for high Swiss needs %.

## API

```python
def compute_split(transactions: list[Transaction]) -> SplitResult:
```

## SplitResult fields

| Field | Description |
|-------|-------------|
| `mode` | `income_based` \| `spend_composition` |
| `needs_pct`, `wants_pct`, `savings_pct` | 0–100 floats |
| `needs_chf`, `wants_chf`, `savings_chf` | CHF amounts |
| `explicit_savings_chf` | Transfers to savings vehicles |
| `residual_savings_chf` | Income minus spending |

## How to extend

- Uses `derive_legacy_bucket()` from `categories.py` when `normalized_category` is set.
- Never let the LLM compute these percentages — always call this tool.
- Update [metrics/needs-wants-savings-split.md](../metrics/needs-wants-savings-split.md) if output shape changes.

## Related pages

- [metrics/needs-wants-savings-split.md](../metrics/needs-wants-savings-split.md)
- [tools/build-dashboard-payload.md](build-dashboard-payload.md)
- [skills/recommend-framework.md](../skills/recommend-framework.md)

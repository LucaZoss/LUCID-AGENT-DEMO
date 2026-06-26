---
type: Metric
title: Needs Wants Savings Split
description: SplitResult from compute_split — CHF amounts and percentages for needs, wants, and savings.
resource: tools/split.py
tags: [metrics, split, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# Needs Wants Savings Split

## Source of truth

- [tools/split.py](../../tools/split.py) — `SplitResult` dataclass, `compute_split()`

## What it does

Primary spending composition metric. Feeds framework recommendations, dashboard charts, and user-facing ratio reports. Two computation modes depending on income presence.

## SplitResult shape

| Field | Type | Description |
|-------|------|-------------|
| `mode` | str | `income_based` \| `spend_composition` |
| `income_chf` | float | Total inflows |
| `needs_chf`, `wants_chf`, `savings_chf` | float | Bucket totals |
| `explicit_savings_chf` | float | VIAC, 3a, etc. |
| `residual_savings_chf` | float | Income minus spending |
| `needs_pct`, `wants_pct`, `savings_pct` | float | 0–100 |

## Persisted snapshots

`split_snapshots` table stores periodic snapshots for dashboard time series.

## How to extend

- Changing percentage semantics requires dashboard + skill copy updates.
- Income/Extras rows from taxonomy are excluded from NWS via `derive_legacy_bucket()`.

## Related pages

- [tools/compute-split.md](../tools/compute-split.md)
- [metrics/dashboard-payload.md](dashboard-payload.md)
- [datasets/category-taxonomy.md](../datasets/category-taxonomy.md)

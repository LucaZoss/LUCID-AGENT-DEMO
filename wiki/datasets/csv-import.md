---
type: Dataset
title: CSV Import
description: Deterministic CSV parsing — column detect, mapping profiles, fingerprints, dedupe, balance reconciliation.
resource: ingest/importer.py
tags: [dataset, csv, etl]
timestamp: 2026-06-26T12:00:00Z
---

# CSV Import

## Source of truth

- [ingest/importer.py](../../ingest/importer.py) — `import_csv_files()`, rollback, preview
- [ingest/csv_detect.py](../../ingest/csv_detect.py) — column detection
- [ingest/csv_normalize.py](../../ingest/csv_normalize.py) — amount/date parsing
- [ingest/profiles.py](../../ingest/profiles.py) — mapping profile persistence

## What it does

Deterministic CSV ingest pipeline. Not a second `BankingProvider` — writes same `transactions` rows as demo seed. Auto-detects Swiss/English headers, deduplicates by `external_fingerprint`, reconciles account balance.

## Canonical row fields

| Field | Source |
|-------|--------|
| `date` | Parsed from CSV date column |
| `merchant` | Description/payee column |
| `amount` | Single amount or debit/credit columns |
| `currency` | Default CHF |

## Dedupe

Partial unique index on `(account_id, external_fingerprint)`. Re-import skipped unless `force` flag.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `LUCID_IMPORT_DIR` | `data/imports` | CSV scan folder |
| `LUCID_LEDGER` | `demo` | `import` for CSV-only empty ledger |

## CLI preview

```bash
uv run python -m ingest.cli path/to/export.csv
```

## Related pages

- [tables/import-and-profiles.md](../tables/import-and-profiles.md)
- [agents/etl-loader-agent.md](../agents/etl-loader-agent.md)
- [tools/etl-and-labeller.md](../tools/etl-and-labeller.md)

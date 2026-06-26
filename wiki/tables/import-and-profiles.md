---
type: SQLite Table
title: Import and Profiles
description: CSV mapping profiles and import batch audit trail for dedupe and rollback.
resource: db/db_schema.py
tags: [csv-import, etl]
timestamp: 2026-06-26T12:00:00Z
---

# Import and Profiles

## Source of truth

- [db/db_schema.py](../../db/db_schema.py) — `csv_mapping_profiles`, `import_batches`
- [ingest/profiles.py](../../ingest/profiles.py) — profile CRUD
- [ingest/importer.py](../../ingest/importer.py) — `import_csv_files()`, rollback

## What it does

Persists CSV column mappings so repeat imports auto-apply known formats. `import_batches` records each import run for dedupe, audit, and `/import-rollback`.

## csv_mapping_profiles

| Column | Notes |
|--------|-------|
| `column_map` | JSON: lucid field → CSV header name |
| `sign_rule` | JSON: `single_amount` \| `debit_credit` etc. |
| `header_hash` | SHA256 of normalized header row for fingerprint match |
| `source_label` | User-visible format name |
| `confirmed` | 1 = user explicitly confirmed mapping |
| `use_count` | Successful imports using this profile |
| `category_col` | Optional CSV category column (migration-added) |
| `skip_patterns` | Rows to skip (migration-added) |

## import_batches

| Column | Notes |
|--------|-------|
| `source_path` | Original file path |
| `content_sha256` | File hash — skip re-import unless `force` |
| `mapping_profile_id` | FK to profile used |
| `row_count` | Rows inserted |
| `skipped_duplicate_count` | Dedupe skips |
| `status` | `completed` \| `partial` \| `rolled_back` |

## How to extend

- New mapping fields → profile JSON schema + [tools/etl/column_mapper.py](../../tools/etl/column_mapper.py).
- ETL agent tools in [agents/etl_loader/tools.py](../../agents/etl_loader/tools.py).

## Related pages

- [datasets/csv-import.md](../datasets/csv-import.md)
- [agents/etl-loader-agent.md](../agents/etl-loader-agent.md)
- [tables/transactions.md](transactions.md)

---
type: Convention
title: Adding a DB Column
description: Add column to SCHEMA in db_schema.py plus additive migrate_schema() for existing DBs.
resource: db/db_schema.py
tags: [conventions, sqlite, migrations]
timestamp: 2026-06-26T12:00:00Z
---

# Adding a DB Column

## Source of truth

- [db/db_schema.py](../../db/db_schema.py) — `SCHEMA`, `migrate_schema()`, `init_db()`
- Tests: [tests/test_ingest_csv.py](../../tests/test_ingest_csv.py) — migration idempotency

## What it does

Schema changes are additive. New databases get columns from `SCHEMA`; existing databases get them from `migrate_schema()`. There is no Alembic — migrations are inline Python.

## Checklist

1. Add column to the `CREATE TABLE` block in `SCHEMA` (with comment documenting values).
2. Add `ALTER TABLE ... ADD COLUMN` guard in `migrate_schema()`:
   - Check `_table_columns(conn, table)` before altering.
   - Guard table existence for tables that may not exist in very old DBs.
3. Update [db/queries.py](../../db/queries.py) row mappers if the column is read/written.
4. Update [contracts.py](../../contracts.py) if the column maps to a DTO field.
5. Add migration test: old DB without column → `migrate_schema()` → column exists.
6. Update relevant [wiki/tables/](../tables/) page.

## Pattern

```python
cols = _table_columns(conn, "transactions")
if "new_column" not in cols:
    conn.execute("ALTER TABLE transactions ADD COLUMN new_column TEXT")
```

## Rules

- Migrations must be **idempotent** — safe to run multiple times.
- Never drop columns in the demo — additive only.
- Column shapes matter more than SQLite vs Postgres — design for future swap.

## Known gap

`transactions.clean_name` exists in schema but is not yet on the `Transaction` dataclass. When adding columns, keep DTO and schema in sync.

## Related pages

- [tables/transactions.md](../tables/transactions.md)
- [architecture/memory-layers.md](../architecture/memory-layers.md)
- [conventions/testing.md](testing.md)

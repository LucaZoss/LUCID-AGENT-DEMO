---
type: Convention
title: Testing
description: pytest suite in tests/; run with pytest -q; pythonpath includes project root.
resource: pyproject.toml
tags: [conventions, pytest, testing]
timestamp: 2026-06-26T12:00:00Z
---

# Testing

## Source of truth

- [pyproject.toml](../../pyproject.toml) — `[tool.pytest.ini_options]`
- [tests/](../../tests/) — 15+ test modules

## What it does

Every deterministic tool and ingest path has pytest coverage. Tests use pytest only (not unittest). Run before any PR.

## Running tests

```bash
uv sync
pytest -q
```

Or with uv:

```bash
uv run pytest -q
```

## Layout

| Pattern | Example |
|---------|---------|
| Tool tests | `tests/test_tools.py`, `tests/test_split.py` |
| Ingest tests | `tests/test_ingest_csv.py` |
| Agent tests | `tests/test_startup.py`, `tests/test_skill_loader.py` |
| Bank tests | `tests/test_bank.py` |

## Conventions

- Type hints on all test functions.
- Docstrings on test modules and non-trivial test functions.
- Use `TYPE_CHECKING` imports for pytest fixtures when needed:
  `CaptureFixture`, `FixtureRequest`, `LogCaptureFixture`, `MonkeyPatch`, `MockerFixture`.
- Use `tmp_path` or in-memory SQLite (`init_db(":memory:")`) for DB tests.
- Migration tests: create minimal old schema, run `migrate_schema()`, assert column exists.

## Rules

- Every new tool → new or extended test file.
- Do not skip tests with `--no-verify` unless user explicitly requests.
- Test real behavior, not mock-only tautologies.

## How to extend

- Add `tests/test_<feature>.py` alongside the feature.
- For DB changes, extend `test_migrate_schema_idempotent` patterns in `test_ingest_csv.py`.

## Related pages

- [conventions/adding-a-tool.md](adding-a-tool.md)
- [conventions/adding-a-db-column.md](adding-a-db-column.md)

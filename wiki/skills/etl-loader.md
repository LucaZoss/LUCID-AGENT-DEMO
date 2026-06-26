---
type: Skill
title: etl_loader
description: SKILL guidance for CSV import — discover files, mapping HITL, normalize, store transactions.
resource: skills/etl_loader/SKILL.md
tags: [skills, etl, csv]
timestamp: 2026-06-26T12:00:00Z
---

# etl_loader

## Source of truth

- [skills/etl_loader/SKILL.md](../../skills/etl_loader/SKILL.md)
- [agents/etl_loader/agent.py](../../agents/etl_loader/agent.py) — actual agent implementation

## What it does

Skill guidance for the ETL loader agent (Agent 1). Covers CSV discovery, format profile lookup by header fingerprint, HITL column-mapping dialog for new formats, row normalization, and transaction storage.

## Note for coding agents

The ETL **agent** in `agents/etl_loader/` is the runtime implementation. This skill documents the procedure; changes to import logic go in `ingest/` and `agents/etl_loader/tools.py`, not in the router.

## Key tools (agent)

- `scan_folder`, `lookup_format_profile`, `import_file`, `save_format_profile`

## Related pages

- [agents/etl-loader-agent.md](../agents/etl-loader-agent.md)
- [datasets/csv-import.md](../datasets/csv-import.md)
- [tables/import-and-profiles.md](../tables/import-and-profiles.md)

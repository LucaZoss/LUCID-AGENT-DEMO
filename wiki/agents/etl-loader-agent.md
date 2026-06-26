---
type: Agent
title: ETL Loader Agent
description: Agent 1 — CSV discovery, format profile lookup, HITL mapping, import to transactions table.
resource: agents/etl_loader/agent.py
tags: [agents, etl, csv]
timestamp: 2026-06-26T12:00:00Z
---

# ETL Loader Agent

## Source of truth

- [agents/etl_loader/agent.py](../../agents/etl_loader/agent.py) — `run_etl_loader_agent()`, `run_etl_pipeline()`
- [agents/etl_loader/tools.py](../../agents/etl_loader/tools.py)
- [ingest/importer.py](../../ingest/importer.py)

## What it does

First agent in CSV startup pipeline. Scans import folder, matches header fingerprints to saved profiles, runs HITL column mapping for unknown formats, imports rows to `transactions` with dedupe fingerprints.

## Key entry points

```python
run_etl_loader_agent(...)
run_etl_pipeline(...)
```

## Tools

`scan_folder`, `check_complexity`, `lookup_format_profile`, `import_file`, `save_format_profile`

## How to extend

- Deterministic import logic → `ingest/` not agent file.
- New CSV heuristics → `tools/etl/column_mapper.py`.
- Does not use budgeting router or skills manifest (has own skill doc for guidance).

## Related pages

- [skills/etl-loader.md](../skills/etl-loader.md)
- [datasets/csv-import.md](../datasets/csv-import.md)
- [architecture/startup-pipeline.md](../architecture/startup-pipeline.md)

---
type: CLI
title: Environment Variables
description: LUCID_* runtime config and LLM provider API keys for local development.
resource: llm/config.py
tags: [cli, environment, config]
timestamp: 2026-06-26T12:00:00Z
---

# Environment Variables

## Source of truth

- [llm/config.py](../../llm/config.py) — LLM detection and `.env` bootstrap
- [orchestrator/repl.py](../../orchestrator/repl.py) — `LUCID_*` vars
- [REPL_README.md](../../REPL_README.md)

## What it does

Runtime configuration without code changes. Shell-exported vars win over `.env` file values.

## LUCID variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LUCID_DB_PATH` | `:memory:` | SQLite file path; `:memory:` = no persistence |
| `LUCID_IMPORT_DIR` | `data/imports` | CSV scan folder |
| `LUCID_LEDGER` | `demo` | `demo` = seed data; `import` = empty ledger for CSV |

## LLM provider variables

Detection order in [llm/config.py](../../llm/config.py):

| Variable | Provider |
|----------|----------|
| `LLAMACPP_URL` | llama.cpp (default `:8080`) |
| `ANTHROPIC_API_KEY` | Anthropic |
| `OPENAI_API_KEY` | OpenAI |
| `GOOGLE_API_KEY` | Google |
| `OLLAMA_URL` | Ollama (default `:11434`) |

`.env` file at project root is loaded at import time (no external dotenv dependency).

## Example session

```bash
export LUCID_DB_PATH=lucid_demo.db
export LUCID_IMPORT_DIR=data/imports
export ANTHROPIC_API_KEY=sk-...
uv run lucid-agent
```

## Rules for coding agents

- Never commit `.env` or API keys.
- New env vars → document here + read in one config module.
- `.gitignore` excludes `.env` and `*.db`.

## Related pages

- [cli/repl-slash-commands.md](repl-slash-commands.md)
- [conventions/imports-and-wiring.md](../conventions/imports-and-wiring.md)
- [architecture/startup-pipeline.md](../architecture/startup-pipeline.md)

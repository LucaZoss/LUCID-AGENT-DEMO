---
type: Architecture
title: Layer Rules
description: Interface boundaries — BankingProvider, LLMProvider, tools vs skills, ingest vs bank.
resource: CLAUDE.md
tags: [architecture, interfaces, constraints]
timestamp: 2026-06-26T12:00:00Z
---

# Layer Rules

## Source of truth

- [CLAUDE.md](../../CLAUDE.md) — architecture section
- [bank/provider.py](../../bank/provider.py) — `BankingProvider`
- [llm/provider.py](../../llm/provider.py) — `LLMProvider`
- [skills/skill_loader.py](../../skills/skill_loader.py) — skill manifest contract

## What it does

The codebase enforces strict layer boundaries so providers and procedures can be swapped without touching business logic. Coding agents must respect these boundaries when adding or refactoring code.

## Rules by layer

### Bank access

- All bank reads go through `BankingProvider` only.
- Never import `SimulatedBank` or `SixBank` outside the config/wiring layer (`orchestrator/startup.py`, demos).
- `ingest/` writes directly to SQLite `transactions` — it is **not** a second `BankingProvider`.

### LLM access

- All LLM calls go through `LLMProvider` only.
- Vendor SDKs (`anthropic`, `openai`, etc.) live **only** in `llm/adapters/`.
- Default adapter wraps LiteLLM for provider agnosticism.

### Tools vs skills

| Layer | What | Example |
|-------|------|---------|
| **Tools** | Pure deterministic Python | `compute_split`, `check_budget` |
| **Skills** | LLM judgment / multi-step procedures | `goal_intake`, `build_budget` |

- If the model is computing a ratio or required monthly saving, that is a **bug** — move logic to `tools/`.
- Skills are loaded two-stage: manifest scan (`list_skills`) → full read on demand (`read_skill`).

### Agents vs router

| Component | Uses router/skills? | Purpose |
|-----------|---------------------|---------|
| `orchestrator/router.py` | Yes | Budgeting conversation loop |
| `agents/ledger_categorizer.py` | **No** | Taxonomy proposals → `category_proposals` |
| `agents/etl_loader/` | **No** | CSV import pipeline |
| `agents/labeller/` | **No** | Merchant cleaning + line categories |

Never route ledger categorization through budgeting skills.

## How to extend

- New deterministic logic → `tools/` + `tests/test_*.py`.
- New conversational procedure → `skills/<name>/SKILL.md` + register in skill_loader scan path.
- New bank source → implement `BankingProvider`; wire in startup only.
- New LLM vendor → new adapter in `llm/adapters/`; wire via `llm/config.py`.

## Related pages

- [overview.md](overview.md)
- [conventions/adding-a-tool.md](../conventions/adding-a-tool.md)
- [conventions/adding-a-skill.md](../conventions/adding-a-skill.md)
- [conventions/imports-and-wiring.md](../conventions/imports-and-wiring.md)

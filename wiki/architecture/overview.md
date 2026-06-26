---
type: Architecture
title: Project Overview
description: LLM-provider-agnostic personal finance agent in CHF with simulated bank and SQLite ledger.
resource: CLAUDE.md
tags: [architecture, overview]
timestamp: 2026-06-26T12:00:00Z
---

# Project Overview

## Source of truth

- [CLAUDE.md](../../CLAUDE.md) — primary architecture document
- Entry point: `uv run lucid-agent` → [orchestrator/repl.py](../../orchestrator/repl.py)
- Package config: [pyproject.toml](../../pyproject.toml)

## What it does

LUCID-AGENT-DEMO is an LLM-provider-agnostic personal finance agent. It helps users define budgets, categorizes transactions, and feeds a dashboard. The demo runs against a **simulated bank** (real SIX Swiss open-banking comes later behind the same `BankingProvider` interface). Currency is **CHF**; amounts are **negative for outflows**.

Coding agents touch five main areas: `tools/` (deterministic math), `skills/` (LLM judgment), `agents/` (separate onboarding loops), `db/` (authoritative state), and `orchestrator/` (wiring + REPL).

## Component map

```mermaid
flowchart TD
    subgraph codingAgents [Coding Agent Touch Points]
        Tools[tools/]
        Skills[skills/]
        Agents[agents/]
        DB[db/]
        Wiring[orchestrator + bank + llm wiring]
    end

    REPL[orchestrator/repl.py] --> Startup[orchestrator/startup.py]
    Startup --> ETLAgent[agents/etl_loader]
    Startup --> LabAgent[agents/labeller]
    REPL --> Router[orchestrator/router.py]
    Router --> Skills
    Router --> Tools
    REPL --> LedgerAgent[agents/ledger_categorizer]
    ETLAgent --> DB
    LabAgent --> DB
    LedgerAgent --> DB
    Router --> DB
    Tools --> DB
```

## Key directories

| Path | Role |
|------|------|
| `bank/` | `BankingProvider` interface + `SimulatedBank`, `DBBankingProvider` |
| `llm/` | `LLMProvider` interface + LiteLLM adapter |
| `tools/` | Deterministic functions — money math, categorization, dashboard |
| `skills/` | `SKILL.md` procedures loaded by router |
| `agents/` | Separate LLM loops (ETL, labeller, ledger categorizer) |
| `ingest/` | Deterministic CSV parsing (not a second bank) |
| `db/` | SQLite schema and query helpers |
| `orchestrator/` | REPL, router, context assembly, startup |
| `tests/` | pytest suite — every new tool needs a test |

## How to extend

- Add features in the layer that owns the concern (see [layer-rules.md](layer-rules.md)).
- Never bypass interfaces to "save time" — swapping simulator for SIX must stay a one-line wiring change.
- Read [conventions/](../conventions/) before your first PR.

## Related pages

- [layer-rules.md](layer-rules.md)
- [memory-layers.md](memory-layers.md)
- [startup-pipeline.md](startup-pipeline.md)
- [conventions/imports-and-wiring.md](../conventions/imports-and-wiring.md)

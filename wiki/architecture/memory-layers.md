---
type: Architecture
title: Memory Layers
description: Four distinct DB memory layers; structured state is authoritative, LLM context is derived.
resource: db/db_schema.py
tags: [architecture, memory, sqlite]
timestamp: 2026-06-26T12:00:00Z
---

# Memory Layers

## Source of truth

- [db/db_schema.py](../../db/db_schema.py) — schema maps directly to memory layers
- [orchestrator/context_assembler.py](../../orchestrator/context_assembler.py) — per-turn context rebuild

## What it does

Structured state lives in SQLite and is **authoritative**. LLM context is a derived, lossy view assembled fresh per request. Never treat conversation history as the source of truth for facts.

## Four layers

### Layer 1 — Durable user facts

| Table | Contents |
|-------|----------|
| `users` | Identity, Telegram chat ID |
| `goals` | `structured_goal` — type, amount, date, engagement, framework |
| `budgets` | Category allocations + target ratios per period |
| `prefs` | Quiet hours, push caps, persona |

Output of onboarding; read by deterministic tools.

### Layer 2 — Financial history (ledger)

| Table | Contents |
|-------|----------|
| `accounts` | Bank accounts and balances |
| `transactions` | Every movement (CSV import or simulated bank) |
| `split_snapshots` | Periodic needs/wants/savings snapshots for charts |
| `category_proposals` | Ledger agent proposals (pending HIL) |
| `merchant_category_overrides` | Learned merchant → category mappings |

Queried with SQL/pandas. **Never** use embeddings over transactions.

### Layer 3 — Conversational memory

| Table | Contents |
|-------|----------|
| `conversations` | Conversation sessions |
| `messages` | Individual turns (user/assistant/tool) |
| `conversation_summary` | Compressed older turns (one row per user) |

### Layer 4 — Agent-learned preferences

| Table | Contents |
|-------|----------|
| `learned_preferences` | Structured suppress rules (e.g. dismissed dining alert) |

Guardrail: safety alerts (breach, goal-risk) are **never** suppressible.

### Additional state

| Table | Contents |
|-------|----------|
| `pending_notifications` | Actionable notification rows awaiting user reply |
| `csv_mapping_profiles` | Persisted CSV column mappings |
| `import_batches` | Import audit trail |

## Per-turn context assembly

```
system prompt
+ user profile (DB: goal, framework, prefs)
+ current financial snapshot (tools run FRESH)
+ running conversation summary
+ last N turns verbatim
+ current user message
```

Tools run fresh each turn — the agent reasons over today's numbers, not stale remembered figures.

## How to extend

- New user fact → Layer 1 table + update `context_assembler.py` + possibly `contracts.py`.
- New ledger field → `transactions` or related table; see [conventions/adding-a-db-column.md](../conventions/adding-a-db-column.md).
- Do not store financial facts only in `messages` — persist to structured tables.

## Related pages

- [tables/transactions.md](../tables/transactions.md)
- [tables/conversation-and-prefs.md](../tables/conversation-and-prefs.md)
- [contracts/structured-goal.md](../contracts/structured-goal.md)

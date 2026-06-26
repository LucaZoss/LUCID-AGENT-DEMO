---
type: SQLite Table
title: Conversation and Prefs
description: Dialogue memory, learned preferences, user prefs, and pending notification state.
resource: db/db_schema.py
tags: [memory, notifications, preferences]
timestamp: 2026-06-26T12:00:00Z
---

# Conversation and Prefs

## Source of truth

- [db/db_schema.py](../../db/db_schema.py)
- [orchestrator/context_assembler.py](../../orchestrator/context_assembler.py)

## What it does

Covers Layer 3 (conversational memory), Layer 4 (learned preferences), user notification prefs, and actionable notification state. Conversation is derived context — not authoritative for financial facts.

## users + prefs

| Table | Key fields |
|-------|------------|
| `users` | `display_name`, `telegram_chat_id` |
| `prefs` | `quiet_hours` (JSON), `max_pushes_day`, `digest_time`, `persona` |

## Conversational memory

| Table | Purpose |
|-------|---------|
| `conversations` | Session container |
| `messages` | `role`: user \| assistant \| tool |
| `conversation_summary` | One compressed summary per user |

## learned_preferences

Structured suppress rules (e.g. `kind=suppress_alert`, `subject=dining_80pct`). `suppressible=0` for safety alerts that must never be silenced.

## pending_notifications

| Column | Notes |
|--------|-------|
| `tier` | `actionable` — only tier needing replies |
| `offered_actions` | JSON of Telegram inline buttons |
| `status` | `awaiting` \| `resolved` \| `expired` |

## Notification tiers (design)

| Tier | Behavior |
|------|----------|
| Silent | Dashboard only |
| Informational | Batched digest |
| Actionable | Immediate push + `diagnose_overspend` skill |

## How to extend

- New preference kinds → structured rows in `learned_preferences`, not free-text LLM memory.
- Notification frequency caps and quiet hours are deterministic config in `prefs`, not agent logic.

## Related pages

- [architecture/memory-layers.md](../architecture/memory-layers.md)
- [skills/diagnose-overspend.md](../skills/diagnose-overspend.md)
- [agents/budgeting-router.md](../agents/budgeting-router.md)

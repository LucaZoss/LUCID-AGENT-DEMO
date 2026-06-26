---
type: Agent
title: Labeller Agent
description: Agent 2 — assigns clean_name and line_category to imported outflows; merchant memory tiers.
resource: agents/labeller/agent.py
tags: [agents, labeller, categorization]
timestamp: 2026-06-26T12:00:00Z
---

# Labeller Agent

## Source of truth

- [agents/labeller/agent.py](../../agents/labeller/agent.py) — `run_labeller_agent()`
- [agents/labeller/tools.py](../../agents/labeller/tools.py)
- [agents/labeller/rules_flow.py](../../agents/labeller/rules_flow.py) — merchant rules HITL

## What it does

Second agent in CSV pipeline. Fetches unlabelled outflows, proposes `clean_name` and `line_category`, applies labels. Rules review flow creates durable `merchant_category_overrides`.

## Tools

`fetch_unlabelled`, `propose_line_category`, `apply_labels`

## Distinction

Does **not** set `normalized_category` — that is the ledger categorizer's job.

## How to extend

- Name cleaning rules → [tools/labeller/name_cleaner.py](../../tools/labeller/name_cleaner.py).
- Bucket logic → [tools/labeller/bucket_classifier.py](../../tools/labeller/bucket_classifier.py).

## Related pages

- [skills/labeller.md](../skills/labeller.md)
- [agents/budget-onboarding.md](budget-onboarding.md)
- [tables/categorization.md](../tables/categorization.md)

---
type: Skill
title: labeller
description: SKILL guidance for merchant cleaning and need/want/savings bucket classification with memory tiers.
resource: skills/labeller/SKILL.md
tags: [skills, labeller, categorization]
timestamp: 2026-06-26T12:00:00Z
---

# labeller

## Source of truth

- [skills/labeller/SKILL.md](../../skills/labeller/SKILL.md)
- [agents/labeller/agent.py](../../agents/labeller/agent.py)

## What it does

Skill guidance for the Labeller agent (Agent 2). Cleans merchant names (`clean_name`) and assigns `line_category` on outflows. Uses `merchant_category_overrides` for auto-apply; confidence-tiered batch confirmation for new merchants.

## Distinction from ledger categorizer

| Agent | Sets | Bucket |
|-------|------|--------|
| Labeller | `clean_name`, `line_category` | need/want/savings via rules |
| Ledger categorizer | `normalized_category` | Full taxonomy proposals |

## Related pages

- [agents/labeller-agent.md](../agents/labeller-agent.md)
- [tools/etl-and-labeller.md](../tools/etl-and-labeller.md)
- [tables/categorization.md](../tables/categorization.md)

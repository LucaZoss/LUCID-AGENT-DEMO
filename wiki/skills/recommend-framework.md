---
type: Skill
title: recommend_framework
description: Suggest saving approach from goal and computed spending ratios; plain language only.
resource: skills/recommend_framework/SKILL.md
tags: [skills, frameworks, budgeting]
timestamp: 2026-06-26T12:00:00Z
---

# recommend_framework

## Source of truth

- [skills/recommend_framework/SKILL.md](../../skills/recommend_framework/SKILL.md)

## What it does

Routes user to `50_30_20`, `zero_based`, or `pay_first` based on goal type and engagement. Must call `compute_split` on real transaction history before advising — never assume ratios.

## Framework routing

| User goal | Framework |
|-----------|-----------|
| Open-ended | Pay-yourself-first or 50/30/20 |
| Specific target + date | Zero-based |
| High engagement / wants control | Zero-based |
| Low engagement | Pay-yourself-first |

## Rules for coding agents

- Never reveal internal methodology names to the user in UI copy.
- Ground recommendations in `compute_split` output from last ~90 days.
- Persist chosen framework to `goals.framework` via deterministic write.

## Related pages

- [tables/goals.md](../tables/goals.md)
- [tools/compute-split.md](../tools/compute-split.md)
- [skills/build-budget.md](build-budget.md)

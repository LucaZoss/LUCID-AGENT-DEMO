---
type: Convention
title: Adding a Skill
description: Create skills/name/SKILL.md with YAML frontmatter; loaded two-stage by skill_loader.
resource: skills/skill_loader.py
tags: [conventions, skills, router]
timestamp: 2026-06-26T12:00:00Z
---

# Adding a Skill

## Source of truth

- [skills/skill_loader.py](../../skills/skill_loader.py) — `list_skills()`, `read_skill()`
- Existing skills: [skills/goal_intake/SKILL.md](../../skills/goal_intake/SKILL.md)

## What it does

Skills are LLM judgment procedures stored as `SKILL.md` files. The router discovers them cheaply (frontmatter only), then loads full instructions only after committing to a skill.

## Checklist

1. Create `skills/<name>/SKILL.md` where `<name>` matches the `name` frontmatter field.
2. Add required YAML frontmatter (see below).
3. Write executable guidance: which tools to call, in what order, expected output format.
4. Add tool definitions in [llm/tool_definitions.py](../../llm/tool_definitions.py) if the skill needs new tools.
5. Add wiki page under [wiki/skills/](../skills/).

## Frontmatter contract

```yaml
---
name: my_skill
description: "One sentence for router skill selection."
triggers: ["example phrase", "another trigger"]
tools_required: [compute_split, check_budget]
outputs: structured_output_name
---
```

| Field | Required | Purpose |
|-------|----------|---------|
| `name` | Yes | Directory name; used by `read_skill(name)` |
| `description` | Yes | Router matching — keep to one sentence |
| `triggers` | Recommended | Example phrases (informational) |
| `tools_required` | Recommended | Tools the skill expects |
| `outputs` | Recommended | What gets persisted or handed off |

## Rules

- Never load every skill's full body at once — manifest scan only in `list_skills()`.
- Skills route the agent; they do not replace tools for arithmetic.
- Re-read full SKILL.md when iterating — only manifest is cached.

## How to extend

- Hand off between skills explicitly in the SKILL.md body (e.g. goal_intake → recommend_framework).
- Do not put deterministic math instructions in skills — reference tool names instead.

## Related pages

- [architecture/layer-rules.md](../architecture/layer-rules.md)
- [agents/budgeting-router.md](../agents/budgeting-router.md)
- [skills/goal-intake.md](../skills/goal-intake.md)

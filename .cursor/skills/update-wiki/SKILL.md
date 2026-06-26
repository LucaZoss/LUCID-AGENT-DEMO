---
name: update-wiki
description: Updates the LUCID-AGENT-DEMO wiki/ knowledge base when code, schema, tools, skills, agents, metrics, or CLI changes. Use when adding or modifying features, architecture, DB tables, contracts, REPL commands, env vars, or when the user asks to update, sync, or document the wiki.
---

# Update Wiki

Keep `wiki/` in sync with code changes. The wiki is **developer documentation for coding agents** — not runtime context for the finance REPL.

## When to update

| Code change | Wiki action |
|-------------|-------------|
| New/changed tool in `tools/` | Update or create `wiki/tools/<name>.md` |
| New/changed skill | Update or create `wiki/skills/<name>.md`; link to `skills/<name>/SKILL.md` |
| New/changed agent | Update or create `wiki/agents/<name>.md` |
| DB column/table | Update `wiki/tables/`; follow [adding-a-db-column.md](../../wiki/conventions/adding-a-db-column.md) |
| DTO in `contracts.py` | Update `wiki/contracts/<name>.md` |
| Metric/result type | Update `wiki/metrics/<name>.md` |
| CSV/taxonomy/bank data | Update `wiki/datasets/` |
| REPL slash command or env var | Update `wiki/cli/` |
| Architecture boundary change | Update `wiki/architecture/` and [CLAUDE.md](../../CLAUDE.md) if rules changed |

**Always** add a row to [wiki/INDEX.md](../../wiki/INDEX.md) when creating a new page.

## Workflow

```
Task Progress:
- [ ] Identify affected wiki folder (see reference.md)
- [ ] Read the source-of-truth file(s) in the repo
- [ ] Update or create the wiki page(s)
- [ ] Update INDEX.md description row if new page
- [ ] Set timestamp to today (ISO 8601 UTC)
- [ ] Run validation (see Step 4)
```

### Step 1: Frontmatter (required on every page)

Every `.md` file **must** start with:

```yaml
---
type: Tool
title: compute_split
description: One sentence for INDEX listing and agent scanning.
resource: tools/split.py
tags: [tools, metrics]
timestamp: 2026-06-26T12:00:00Z
---
```

- `resource` — canonical repo path (not external URLs)
- `description` — must match the one-line summary in INDEX.md
- `timestamp` — bump on every substantive edit

Full `type` taxonomy: [reference.md](reference.md)

### Step 2: Page body template

Use this structure (imperative, constraint-focused):

```markdown
# Title

## Source of truth
- path/to/file.py — brief role

## What it does
2–4 sentences.

## Key fields / API
Table or bullet list.

## How to extend
What to change, what NOT to change, which test file to update.

## Related pages
- [other-page](../folder/other-page.md)
```

Do **not** paste full SKILL.md bodies — summarize and link to `skills/*/SKILL.md`.

### Step 3: INDEX.md

Add new pages under the correct section table in [wiki/INDEX.md](../../wiki/INDEX.md):

```markdown
| [page-name](folder/page-name.md) | Same text as frontmatter description |
```

### Step 4: Validate

Before finishing, verify:

1. Every `wiki/**/*.md` file starts with complete YAML frontmatter (all six keys).
2. Every link in `wiki/INDEX.md` points to an existing file.
3. Every wiki page except `INDEX.md` has a row in the correct INDEX section table.
4. `description` in frontmatter matches the INDEX table row.

Run from repo root if you add a validator script later; until then, spot-check with `glob wiki/**/*.md` and read INDEX.md.

## Rules

- Wiki complements [CLAUDE.md](../../CLAUDE.md); do not duplicate it wholesale.
- Cross-links use relative paths within `wiki/` (e.g. `../tools/compute-split.md`).
- No runtime `wiki_loader` — static markdown only unless the user explicitly requests wiring.
- Do not edit plan files in `.cursor/plans/` as part of wiki updates.

## Additional resources

- Folder routing and type taxonomy: [reference.md](reference.md)
- Existing conventions: [wiki/conventions/](../../wiki/conventions/)

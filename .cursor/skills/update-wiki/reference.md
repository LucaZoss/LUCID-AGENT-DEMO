# Wiki Reference

## Type taxonomy

| type | Use for | Example path |
|------|---------|--------------|
| `Index` | `wiki/INDEX.md` only | `wiki/INDEX.md` |
| `Architecture` | Design, constraints, data flow | `wiki/architecture/overview.md` |
| `Convention` | Coding rules | `wiki/conventions/adding-a-tool.md` |
| `SQLite Table` | DB tables | `wiki/tables/transactions.md` |
| `Dataclass` | DTOs in `contracts.py` | `wiki/contracts/transaction.md` |
| `Tool` | `tools/` functions | `wiki/tools/compute-split.md` |
| `Skill` | `skills/*/SKILL.md` summaries | `wiki/skills/goal-intake.md` |
| `Agent` | `agents/` LLM loops | `wiki/agents/ledger-categorizer.md` |
| `Interface` | `BankingProvider`, `LLMProvider` | (create under `architecture/` if needed) |
| `Metric` | Computed outputs | `wiki/metrics/budget-breach.md` |
| `Dataset` | CSV, taxonomy, demo data | `wiki/datasets/csv-import.md` |
| `CLI` | REPL commands, env vars | `wiki/cli/environment-variables.md` |

## Folder routing

| If you changed… | Update… |
|-----------------|---------|
| `db/db_schema.py` | `wiki/tables/` (+ `contracts/` if DTO changed) |
| `contracts.py` | `wiki/contracts/` |
| `tools/*.py` | `wiki/tools/` (+ `wiki/metrics/` if result type changed) |
| `skills/*/SKILL.md` | `wiki/skills/` |
| `agents/*` | `wiki/agents/` |
| `categories.py` | `wiki/datasets/category-taxonomy.md` |
| `ingest/` | `wiki/datasets/csv-import.md`, `wiki/tables/import-and-profiles.md` |
| `orchestrator/repl.py` | `wiki/cli/repl-slash-commands.md` |
| `llm/config.py`, env vars | `wiki/cli/environment-variables.md` |
| `orchestrator/startup.py` | `wiki/architecture/startup-pipeline.md` |
| `orchestrator/router.py` | `wiki/agents/budgeting-router.md` |

## File naming

- Use kebab-case: `compute-split.md`, `goal-intake.md`
- One primary concept per page; group related small tables (e.g. `import-and-profiles.md`)

## Source files to read before writing

| Topic | Read first |
|-------|------------|
| Architecture rules | `CLAUDE.md`, `wiki/architecture/layer-rules.md` |
| DB schema | `db/db_schema.py` |
| DTOs | `contracts.py` |
| REPL / env | `REPL_README.md`, `orchestrator/repl.py` |
| Ledger HIL | `docs/IMPORT_AND_LEDGER_CATEGORIZATION.md` |

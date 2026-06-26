---

## type: Index
title: LUCID Agent Wiki
description: Entry point for coding agents building LUCID-AGENT-DEMO.
resource: wiki/INDEX.md
tags: [index, coding-agents]
timestamp: 2026-06-26T12:00:00Z

# LUCID Agent Wiki

Knowledge base for **coding agents** (Cursor, Claude, etc.) extending this repository. Complements [CLAUDE.md](../CLAUDE.md); start here for navigable, task-focused reference.

## How to use this wiki

1. Read [architecture/overview.md](architecture/overview.md) before any structural change.
2. Check [conventions/](conventions/) before adding tools, skills, DB columns, or tests.
3. Use [tables/](tables/) and [contracts/](contracts/) when touching SQLite schema or DTOs.

## Quick rules (non-negotiable)

1. **Bank access** — only through `BankingProvider`; never import `SimulatedBank` / `SixBank` outside config/wiring.
2. **LLM access** — only through `LLMProvider`; vendor SDKs live in `llm/adapters/` only.
3. **Money math** — deterministic in `tools/`; the LLM never computes ratios or savings amounts.
4. **Authoritative state** — SQLite (`db/`); conversation history is a derived view, not source of truth.
5. **Ledger agent ≠ router** — `agents/ledger_categorizer.py` is a separate loop; it does not use `orchestrator/router.py` or budgeting skills.

---

## Architecture


| Page                                                 | Description                                                |
| ---------------------------------------------------- | ---------------------------------------------------------- |
| [overview](architecture/overview.md)                 | Project purpose, CHF conventions, high-level component map |
| [layer-rules](architecture/layer-rules.md)           | Interface boundaries: bank, LLM, tools vs skills           |
| [memory-layers](architecture/memory-layers.md)       | Four DB memory layers and what is authoritative            |
| [startup-pipeline](architecture/startup-pipeline.md) | CSV path: ETL → labeller → rules → onboarding → REPL       |


## Conventions


| Page                                                    | Description                                                  |
| ------------------------------------------------------- | ------------------------------------------------------------ |
| [adding-a-tool](conventions/adding-a-tool.md)           | Pure Python tools, pytest required, no LLM arithmetic        |
| [adding-a-skill](conventions/adding-a-skill.md)         | SKILL.md frontmatter and skill_loader two-stage contract     |
| [adding-a-db-column](conventions/adding-a-db-column.md) | SCHEMA + migrate_schema() additive migration pattern         |
| [testing](conventions/testing.md)                       | pytest layout, pythonpath, running tests                     |
| [imports-and-wiring](conventions/imports-and-wiring.md) | Where concrete adapters and bank implementations are allowed |


## Tables (SQLite)


| Page                                                       | Description                                                 |
| ---------------------------------------------------------- | ----------------------------------------------------------- |
| [transactions](tables/transactions.md)                     | Core ledger table — one row per bank movement               |
| [accounts](tables/accounts.md)                             | User bank accounts with balance and type metadata           |
| [goals](tables/goals.md)                                   | Structured financial goals (open or target)                 |
| [budgets](tables/budgets.md)                               | Monthly category allocations and target ratios              |
| [import-and-profiles](tables/import-and-profiles.md)       | CSV mapping profiles and import batch audit trail           |
| [categorization](tables/categorization.md)                 | Category proposals and merchant override memory             |
| [conversation-and-prefs](tables/conversation-and-prefs.md) | Dialogue memory, learned preferences, pending notifications |


## Contracts (dataclasses)


| Page                                            | Description                                             |
| ----------------------------------------------- | ------------------------------------------------------- |
| [transaction](contracts/transaction.md)         | Transaction DTO crossing bank → tools → LLM → dashboard |
| [account](contracts/account.md)                 | Account DTO with type and income flags                  |
| [structured-goal](contracts/structured-goal.md) | Goal DTO with type, engagement, and framework           |
| [budget](contracts/budget.md)                   | Budget DTO with allocations and target ratios           |


## Tools (deterministic)


| Page                                                          | Description                                  |
| ------------------------------------------------------------- | -------------------------------------------- |
| [categorize-transaction](tools/categorize-transaction.md)     | Rule-based need/want/savings classification  |
| [compute-split](tools/compute-split.md)                       | Needs/wants/savings ratio computation        |
| [compute-goal-feasibility](tools/compute-goal-feasibility.md) | Required monthly savings and on-track flag   |
| [check-budget](tools/check-budget.md)                         | Deterministic budget breach detection        |
| [build-dashboard-payload](tools/build-dashboard-payload.md)   | Assembles locked dashboard chart contract    |
| [etl-and-labeller](tools/etl-and-labeller.md)                 | ETL column mapping and labeller helper tools |


## Skills (LLM procedures)


| Page                                                 | Description                                           |
| ---------------------------------------------------- | ----------------------------------------------------- |
| [goal-intake](skills/goal-intake.md)                 | Collect structured goal, engagement, and income       |
| [recommend-framework](skills/recommend-framework.md) | Route to 50/30/20, zero-based, or pay-first           |
| [build-budget](skills/build-budget.md)               | Build CHF allocations grounded in transaction history |
| [diagnose-overspend](skills/diagnose-overspend.md)   | Human sentence + offered action for budget breaches   |
| [etl-loader](skills/etl-loader.md)                   | CSV import skill guidance for the ETL agent           |
| [labeller](skills/labeller.md)                       | Merchant cleaning and bucket classification skill     |


## Agents (separate LLM loops)


| Page                                               | Description                                       |
| -------------------------------------------------- | ------------------------------------------------- |
| [budgeting-router](agents/budgeting-router.md)     | Main orchestrator loop: route → skill → tools     |
| [etl-loader-agent](agents/etl-loader-agent.md)     | Agent 1: CSV discovery, mapping HITL, import      |
| [labeller-agent](agents/labeller-agent.md)         | Agent 2: line categories and clean merchant names |
| [ledger-categorizer](agents/ledger-categorizer.md) | Taxonomy proposals; HIL via /cat-accept           |
| [budget-onboarding](agents/budget-onboarding.md)   | Deterministic post-import onboarding (no LLM)     |


## Metrics (computed outputs)


| Page                                                              | Description                                     |
| ----------------------------------------------------------------- | ----------------------------------------------- |
| [needs-wants-savings-split](metrics/needs-wants-savings-split.md) | SplitResult from compute_split                  |
| [goal-feasibility](metrics/goal-feasibility.md)                   | FeasibilityResult from compute_goal_feasibility |
| [budget-breach](metrics/budget-breach.md)                         | BudgetBreach from check_budget                  |
| [dashboard-payload](metrics/dashboard-payload.md)                 | DashboardPayload UI contract shape              |


## Datasets


| Page                                               | Description                                                 |
| -------------------------------------------------- | ----------------------------------------------------------- |
| [csv-import](datasets/csv-import.md)               | Column detect, fingerprints, dedupe, balance reconciliation |
| [category-taxonomy](datasets/category-taxonomy.md) | Canonical normalized category keys in categories.py         |
| [simulated-bank](datasets/simulated-bank.md)       | SimulatedBank vs DBBankingProvider swap pattern             |


## CLI


| Page                                                  | Description                                       |
| ----------------------------------------------------- | ------------------------------------------------- |
| [repl-slash-commands](cli/repl-slash-commands.md)     | REPL slash commands for import and categorization |
| [environment-variables](cli/environment-variables.md) | LUCID_* and LLM provider env vars                 |



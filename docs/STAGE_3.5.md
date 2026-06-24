# Stage 4 — CSV Import Pipeline, Labeller, Rules Flow & Budget Onboarding

## What this covers

Phase 4: replacing the in-memory demo seed with a real CSV import pipeline, adding two pre-budget agents (ETL Loader and Labeller), a new LLM-assisted HITL rules flow for classifying uncategorized merchants, and a deterministic budget onboarding step that assigns need/want/savings before the REPL opens. The startup sequence is now a formal pipeline of named stages.

---

## Files added / changed

```
LUCID-AGENT-DEMO/
├── ingest/
│   ├── csv_detect.py          # column fingerprinting + header detection
│   ├── csv_normalize.py       # row normalisation (amounts, dates, merchant cleanup)
│   ├── importer.py            # import_csv() — deduplication, batch IDs, DB write
│   ├── profiles.py            # csv_mapping_profiles CRUD (format memory)
│   ├── account_detect.py      # bank/account type detection from headers
│   └── accounts.py            # account upsert helpers
├── tools/
│   ├── etl/
│   │   ├── column_mapper.py       # LLM-assisted column → canonical mapping
│   │   ├── complexity_analyzer.py # heuristic CSV complexity score
│   │   └── normalizer.py          # amount sign normalisation (CHF, negative=outflow)
│   └── labeller/
│       ├── name_cleaner.py        # strip bank noise from merchant strings
│       └── bucket_classifier.py   # pattern rules for line_category assignment
├── agents/
│   ├── etl_loader/
│   │   ├── agent.py           # run_etl_loader_agent() — Scout Pattern HITL importer
│   │   └── tools.py           # scan_csv_folder, check_profile, import_file, …
│   ├── labeller/
│   │   ├── agent.py           # run_labeller_agent() — assigns line_category + clean_name
│   │   ├── tools.py           # fetch_unlabelled, propose_line_category, apply_labels, …
│   │   └── rules_flow.py      # NEW — LLM-assisted HITL merchant rules (see below)
│   └── budget_onboarding/
│       ├── agent.py           # run_budget_onboarding() — deterministic 4-step flow
│       └── tools.py           # fetch_outflow_line_categories, apply_remaining_*, …
├── db/
│   └── db_schema.py           # +csv_mapping_profiles, +import_batches,
│                              #  +category_proposals, +merchant_category_overrides
└── orchestrator/
    ├── startup.py             # formal StartupStage enum + stage_* functions
    └── repl.py                # +/import, /import-rollback, /rules, /rules list,
                               #  /cat-run, /cat-accept, /cat-reject, /review-categories
```

---

## Two-column categorization model

Every transaction row carries two independent labels:

| Column | Values | Set by | Purpose |
|---|---|---|---|
| `line_category` | `groceries`, `transport`, `salary`, … | Labeller Agent or Rules Flow | Descriptive — shown in breakdowns and the dashboard |
| `category` | `need` \| `want` \| `savings` | Budget Onboarding or Rules Flow | Budget bucket — drives `compute_split` and goal tracking |

These are assigned in two separate passes. The Labeller assigns `line_category` only; it never touches `category`. Budget Onboarding assigns `category` only (bulk-classifying anything still NULL). The Rules Flow is the only place that sets both in one step, because the user is confirming a complete rule.

Transactions with `amount > 0` (inflows) always have `category = NULL` — `compute_split` handles them as income, never as budget spending.

---

## Startup pipeline (`orchestrator/startup.py`)

The startup sequence is controlled by a `StartupStage` enum. Each stage is a named function; `run_startup()` calls them in order and updates `state.stage` before each one.

```
StartupStage.MODEL            — auto-detect LLM provider, build adapter
StartupStage.DATA_SOURCE      — select CSV folder or skip (demo mode)
StartupStage.PERSISTENCE      — open / migrate SQLite DB
StartupStage.ETL_LOADER       — import new CSV files (Agent 1)
StartupStage.LABELLER         — assign line_category + clean_name (Agent 2)
StartupStage.RULES_REVIEW     — LLM-assisted merchant rules for unlabeled rows
StartupStage.BUDGET_ONBOARDING — assign need/want/savings if none exist yet
StartupStage.REPL             — open the interactive chat loop
```

The Rules Review stage runs **between the Labeller and Budget Onboarding** — this is the critical ordering. Without it, every unlabeled merchant would be bulk-classified as `want` by onboarding, making the resulting split inaccurate. The rules flow lets the user refine merchant classifications first, so onboarding only sees the residual.

Budget Onboarding is skipped entirely if all transactions already have a `category` (i.e., the user has run the full flow before).

---

## ETL Loader Agent (`agents/etl_loader/`)

Implements the **Scout Pattern**: check memory before asking.

### Flow

```
scan_csv_folder(folder)
  └─ for each .csv file:
       check_profile(headers)        → known profile? use_count >= 2?
       ├─ YES (confirmed) → auto-apply silently
       └─ NO              → show column sample + LLM mapping suggestion → HITL confirm
       import_file(path, mapping)    → dedup by fingerprint, write to transactions
       update_profile(headers, mapping, use_count++)
```

### Format memory (`csv_mapping_profiles`)

Every confirmed column mapping is stored by `header_fingerprint` (sorted SHA-1 of column names). On re-import the same format is recognised and applied without prompting. Profiles require `use_count >= 2` before auto-applying — the first import always asks, the second and onwards are silent.

### Deduplication

Each row is fingerprinted as `SHA-1(date + merchant + amount + account_id)`. Duplicate fingerprints are skipped; the import summary reports how many were inserted vs skipped.

---

## Labeller Agent (`agents/labeller/`)

Assigns `line_category` and `clean_name` to outflow transactions that were imported without a sector column (common with Swiss bank exports).

### Flow

```
fetch_unlabelled(conn, user_id)        → outflows WHERE line_category IS NULL
detect_merchant_patterns(txns)         → group recurring merchants (≥2 occurrences)
for each group / transaction:
    lookup_merchant_memory(merchant)   → check merchant_category_overrides first
    propose_line_category(llm, txn)    → LLM call if no memory hit
batch_confirm_with_user(console, ...)  → HITL table; pattern groups offer rule-saving
apply_labels(conn, confirmed)          → UPDATE transactions + UPSERT overrides
```

### What the Labeller does NOT do

- It does not assign `category` (need/want/savings) — that is Budget Onboarding's job.
- It does not process inflows (`amount > 0`) — salary/refunds are handled by the Rules Flow.
- It does not call the router or use skills.

### Merchant memory (`merchant_category_overrides`)

When the user saves a pattern rule during labelling, the `merchant_normalized` key and its `line_category` are written to `merchant_category_overrides`. On the next import, `lookup_merchant_memory` hits this table first, so confirmed merchants are never re-prompted.

---

## Rules Flow (`agents/labeller/rules_flow.py`)

The main new feature in this stage. An LLM-assisted HITL flow that runs as a startup stage to classify all merchants the Labeller couldn't match, before Budget Onboarding assigns bulk defaults.

### Design decisions

- **Batch upfront, review once**: all LLM proposals are fetched in a single pass (with a Rich progress bar), then displayed in one table. The user does not interact per-merchant during the proposal phase.
- **Table → edit by number**: the user sees all 222 proposals at once, can accept everything with `a`, or type a row number to edit that specific row.
- **Direct assignment syntax**: `b=need l=groceries` sets multiple fields in one line and exits the editor immediately (no re-prompt). Bare `b` or `l` opens an interactive numbered picker.
- **No re-render on every action**: the table is printed once at startup, and again only on explicit `p`. After each edit, a single status line is printed. This prevents the 222-row table from flooding the screen and confusing the outer vs inner prompt context.
- **Bypasses `category_proposals`**: rules are confirmed inline and written directly to `transactions` + `merchant_category_overrides`. There is no staging step.
- **Overrides bulk assignments**: the UPDATE has no `AND category IS NULL` guard — a user-confirmed rule takes precedence over whatever Budget Onboarding previously wrote.

### Query condition

The fetch query uses:
```sql
WHERE (t.category IS NULL OR COALESCE(t.line_category, '') = '')
```
This catches two cases: transactions that were never touched by onboarding (pre-onboarding run), and transactions that were bulk-classified as `want` but still have no descriptive label (post-onboarding run). This makes `/rules` useful at any point in the lifecycle.

### Income and refund handling

Inflows (`amount > 0`) are classified as `type = income` or `type = refund`. For these, `bucket` is set to `NULL` — consistent with how `compute_split` already treats positive-amount rows. Only `line_category` is written (e.g., `salary`, `refund`).

### Table view commands

| Input | Effect |
|---|---|
| `a` or Enter | Accept all pending suggestions and save |
| `<n>` | Open row n in the single-item editor |
| `s<n>` | Skip row n (no rule saved); typing `<n>` again un-skips it |
| `p` | Reprint the full proposals table |
| `/help` | Show the full command reference including valid label names |
| `/quit` | Save rules confirmed so far and exit the flow |

### Row editor commands

| Input | Effect |
|---|---|
| `b=need l=groceries` | Set multiple fields directly; exits editor immediately |
| `b=need` | Set bucket only; exits immediately |
| `b` / `l` / `t` | Open interactive numbered picker for that field; loops back |
| Enter | Accept current values |
| `s` | Skip this merchant |
| `/quit` | Save confirmed rules and exit the flow |

### LLM call

One `llm.complete()` call per merchant group (no tools, text completion only). System prompt requests a JSON-only response:

```json
{
  "type": "income" | "refund" | "expense",
  "bucket": "need" | "want" | "savings" | null,
  "line_category": "<one of 20 valid labels>",
  "rationale": "<one sentence>"
}
```

Invalid or unparseable responses fall back to a deterministic heuristic (`amount > 0` → income, else `expense/want/other`).

---

## Budget Onboarding Agent (`agents/budget_onboarding/`)

Deterministic four-step HITL flow. No LLM.

```
Step 1 — Income identification
  Mark the account as income-bearing; identify salary transactions by amount threshold.

Step 2 — Net balance (optional)
  User can enter their current total capital / savings figure.

Step 3 — Needs classification
  Shows all distinct line_categories present in outflows.
  User selects which ones are essentials (need) — rent, health insurance, etc.
  Writes category = 'need' for all transactions in the selected line_categories.

Step 4 — Auto-classify rest
  apply_remaining_outflows_as_wants()  → category = 'want' for all remaining outflows
  apply_remaining_credits_as_savings() → category = 'savings' for all inflows
```

After this step every transaction has both `line_category` and `category` populated (or at least `category`). The Rules Flow running before this step means Step 3's list contains far fewer "(uncategorised)" entries.

---

## New DB tables (`db/db_schema.py`)

| Table | Purpose |
|---|---|
| `csv_mapping_profiles` | Stores confirmed column mappings by `header_fingerprint`; `use_count` drives auto-apply threshold |
| `import_batches` | One row per import run; links transactions to the source file + timestamp |
| `category_proposals` | Staging area for Labeller proposals before the user accepts via `/cat-accept` |
| `merchant_category_overrides` | Persists user-confirmed merchant → `bucket` + `line_category` rules; hit by both the Labeller and Rules Flow on next import |

---

## New REPL commands (`orchestrator/repl.py`)

| Command | Effect |
|---|---|
| `/import [path]` | Import a CSV file or folder through the ETL Loader |
| `/import-preview <path>` | Show what would be imported without writing to DB |
| `/import-rollback <batch_id>` | Delete all transactions from a specific import batch |
| `/import-mapping` | Show the column mapping profile for the last import |
| `/rules` | Run the LLM-assisted merchant rules flow for unlabeled transactions |
| `/rules list` | Show all saved merchant categorization rules as a Rich table |
| `/review-categories` | List transactions that still have no `line_category` |
| `/cat-run` | Re-run the Labeller Agent against the current DB |
| `/cat-accept <id>` | Accept a specific category proposal from `category_proposals` |
| `/cat-reject <id>` | Reject a category proposal |

---

## Architecture rules enforced

- **Labeller never sets `category`** — the need/want/savings column is owned exclusively by Budget Onboarding (bulk) and the Rules Flow (user-confirmed). These are distinct concerns and must not be conflated.
- **Rules Flow runs before Budget Onboarding** — enforced by the `StartupStage` ordering in `run_startup()`. Swapping this order would cause uncategorized merchants to receive bulk `want` assignments before the user gets to classify them.
- **`merchant_category_overrides` is the source of truth for rules** — both the Labeller's `lookup_merchant_memory` and the Rules Flow's retroactive UPDATE read/write this table. No rule logic lives in conversation history.
- **No LLM arithmetic** — `compute_split` and all budget math are called as deterministic tools. The LLM only proposes classifications and generates natural-language rationale.
- **`BankingProvider` interface untouched** — the CSV ingest pipeline writes the same `transactions` rows as the simulated bank; swapping to SIX open-banking remains a one-line config change.

---

## What is NOT here yet (Phase 5+)

- Notification pipeline (`Notifier` interface, `ConsoleNotifier`, `TelegramNotifier`)
- Telegram webhook + inline button routing for actionable alerts
- Conversation summary compression (rolling older turns into a `conversation_summary` row)
- Full multi-turn skill implementations (`goal_intake`, `build_budget` with DB persistence)
- SIX open-banking adapter behind the `BankingProvider` interface
- Dashboard payload delivery to a frontend

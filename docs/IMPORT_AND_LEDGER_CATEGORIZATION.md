# CSV import and ledger categorization

This document describes how **bank CSV exports** are ingested into the same SQLite ledger as the demo, how **column mappings** are persisted and reused, and how a **separate ledger categorization agent** proposes `need` / `want` / `savings` buckets and fine **line categories** with **human-in-the-loop** confirmation before anything is written to `transactions.category` / `transactions.line_category`.

For day-to-day usage (environment variables and slash commands), see [REPL_README.md](../REPL_README.md). High-level architecture rules live in [CLAUDE.md](../CLAUDE.md).

---

## Design goals

1. **No second `BankingProvider`.** CSV ingestion writes normal `transactions` rows; reads still go through `DBBankingProvider` like today.
2. **Deterministic ingest.** Header detection, decoding, delimiters, amounts, dates, fingerprints, and balance reconciliation are pure Python in `ingest/` — no LLM.
3. **Persisted mapping.** Column layouts are stored per user so later sessions (with a file-backed DB) can skip re-detection when the header hash matches.
4. **Second LLM agent.** Budgeting stays in `orchestrator/router.py` + skills. Tagging outflows uses `agents/ledger_categorizer.py` only, with its own tools and prompts.
5. **HIL for categories.** The model only inserts **proposals** (`category_proposals`). The user applies them via the REPL (`/cat-accept`), which runs deterministic `UPDATE` statements.

---

## Repository layout

| Path | Role |
|------|------|
| [`ingest/csv_detect.py`](../ingest/csv_detect.py) | Header alias scoring, `find_header_row_index`, ambiguity vs resolved mapping, encoding sniff |
| [`ingest/csv_normalize.py`](../ingest/csv_normalize.py) | Decimal and date parsing; signed amount from `single_amount` or `debit_credit` |
| [`ingest/profiles.py`](../ingest/profiles.py) | CRUD for `csv_mapping_profiles` |
| [`ingest/importer.py`](../ingest/importer.py) | `preview_csv_file`, `import_csv_files`, `rollback_import_batch`; uses pandas for dialect-robust reading |
| [`ingest/cli.py`](../ingest/cli.py) | `python -m ingest.cli <file.csv>` — JSON preview for scripts/CI |
| [`agents/ledger_categorizer.py`](../agents/ledger_categorizer.py) | Small `LLMProvider` tool loop (narrow system prompt) |
| [`agents/ledger_tools.py`](../agents/ledger_tools.py) | `propose_spending_bucket`, `propose_line_category`, list/apply/reject proposals |
| [`orchestrator/repl.py`](../orchestrator/repl.py) | Slash-command glue only; no business logic duplication |

---

## Database additions

Defined in [`db/db_schema.py`](../db/db_schema.py). `migrate_schema()` adds new columns on older databases that already had a `transactions` table.

### `csv_mapping_profiles`

Stores a user-named mapping: JSON `column_map` (logical field → exact CSV header), plain-text `sign_rule` (`single_amount` or `debit_credit`), `encoding`, `delimiter`, and `header_hash` for auto-selection on the next import.

### `import_batches`

One row per import attempt per file path: `content_sha256`, counts, `mapping_profile_id`, `status` (`completed` | `partial` | `rolled_back`). Unchanged file bytes skip re-import unless forced.

### `transactions` (extra columns)

| Column | Purpose |
|--------|---------|
| `line_category` | Fine label (e.g. `groceries`, `rent`) after HIL or manual set |
| `import_batch_id` | Links rows to a batch for rollback |
| `external_fingerprint` | SHA-256 of normalized `(date, amount, merchant)` for dedupe |

Partial unique index: `(account_id, external_fingerprint)` when fingerprint is not null.

### `category_proposals`

Pending or terminal rows for the ledger agent. At most one **pending** row per `txn_id` is merged in code (bucket and line updates patch the same row).

### `merchant_category_overrides`

Reserved for future “remember this merchant” behavior; schema is present for extension.

---

## Ingest pipeline

```mermaid
flowchart LR
  subgraph ingest [ingest package]
    A[Read bytes]
    B[Sniff encoding + delimiter]
    C[find_header_row_index]
    D[Resolve mapping]
    E[pandas read_csv header=idx]
    F[Iterate data rows]
  end
  D --> P[(csv_mapping_profiles)]
  F --> T[(transactions)]
  F --> Bt[(import_batches)]
```

**Mapping resolution order** (in `import_csv_files`):

1. Explicit `profile_id` argument (REPL: `/import profile <uuid>`).
2. Profile whose `header_hash` matches the current file header.
3. Auto-detect via `detect_mapping`. If the result is `MappingAmbiguity`, the file is skipped and the reason is returned in `ImportResult`.

**Dedupe:**

- **File level:** same `content_sha256` as a completed batch for that path → skip (unless `force_reimport`).
- **Row level:** same `external_fingerprint` for the account → row not inserted; `skipped_duplicate_count` incremented.

**Balance:** after inserts, `accounts.balance` is set to `SUM(transactions.amount)` for that account (single source of truth).

**Currency:** non-CHF rows are skipped with a warning (demo contract is CHF).

**Income:** imports do not require income rows, but `compute_split` still needs income inside the analysis window — the importer warns when a file has no positive amounts.

---

## CSV dialect robustness

Banks export CSV in wildly different shapes. Three classes of problems previously broke import silently:

| Problem | Example | Old behaviour | Fix |
|---------|---------|---------------|-----|
| Excel separator hint | First line is `sep=;` (UBS MasterCard) | `sep=;` parsed as the header | `find_header_row_index` skips it |
| Multiple metadata rows | Account number, holder, date range before the real header (UBS checking, BCGE) | All rows read as data with wrong columns | `find_header_row_index` scans up to 15 lines |
| Redundant amount columns | CSV has `Amount` **and** `Debit` + `Credit` (UBS MasterCard) | Always picked `debit_credit`; empty Debit/Credit → 0 rows imported | `detect_mapping` samples real data to decide |

### `find_header_row_index` — how it works

Located in `ingest/csv_detect.py`. No bank-specific rules.

```
for each candidate line (up to max_scan=15):
    split by delimiter → cells
    score = Σ best_alias_weight(cell) over all cells
    track line with highest score
```

`best_alias_weight` checks a cell's normalized name against every Lucid field alias table (date, amount, merchant, debit, credit, currency, reference). Metadata rows score near zero because their cells are account numbers, holder names, or date ranges — none of which match field aliases. The actual header row scores high because `Buchungsdatum`, `Betrag`, `Debit`, `Date`, `Booking text`, etc. all match.

The returned index is passed as `header=idx` to `pandas.read_csv`, which skips metadata rows cleanly.

### sign_rule disambiguation

When a CSV has both an `Amount` column **and** separate `Debit` / `Credit` columns, `detect_mapping` takes a sample of up to 20 data rows and counts non-empty values in each:

```python
if amt_filled > max(deb_filled, cred_filled):
    sign_rule = "single_amount"   # e.g. UBS MasterCard
else:
    sign_rule = "debit_credit"    # e.g. PostFinance checking
```

### Encoding detection

`sniff_csv_text` tries `utf-8-sig` → `utf-8` first (covers the majority of modern exports). If both raise `UnicodeDecodeError`, it falls back to `chardet` for legacy encodings (ISO-8859-1, cp1252, etc.). Chardet is intentionally not used first because it can misidentify short UTF-8 texts containing non-ASCII characters as ISO-8859-9 or similar.

### Column alias coverage

`_MERCHANT_ALIASES` and `_DATE_ALIASES` were extended to cover common English bank column names:

| New alias | Field | Score |
|-----------|-------|-------|
| `booking text` | merchant | 0.92 |
| `description` | merchant | 0.85 |
| `narrative` | merchant | 0.80 |
| `purchase date` | date | 0.95 |
| `booked` | date | 0.60 |

### Optional-field tie-breaking

When two columns tie for an optional field (e.g. `Currency` and `Original currency` both match the `"currency"` alias), the shorter header name is picked silently. Ties on required fields (date, merchant, amount) still block import and surface an error.

### Dependencies added

| Package | Why |
|---------|-----|
| `pandas >= 2.0` | Replaces `csv.DictReader`; robust dialect handling, `header=N` to skip metadata rows |
| `chardet >= 4.0` | Encoding detection fallback for non-UTF-8 bank exports |

---

## Ledger categorization agent

- **Entry:** `run_ledger_categorizer(llm, conn, user_id, …)` in [`agents/ledger_categorizer.py`](../agents/ledger_categorizer.py).
- **Tools (OpenAI-style JSON passed to `LLMProvider.complete`):**
  - `propose_spending_bucket` — `need` | `want` | `savings` for an outflow `txn_id`.
  - `propose_line_category` — one of the closed labels in `LINE_CATEGORY_VOCABULARY` in [`agents/ledger_tools.py`](../agents/ledger_tools.py) (aligned with Swiss-style buckets such as `rent`, `health_insurance`, `groceries`, `dining`, …).
- **Not wired** into `llm/tool_definitions.py` or `orchestrator/router.py` — the budgeting agent cannot silently approve categories.

Use **`/setup`** in the REPL for a full checklist covering the import folder, `LUCID_DB_PATH` / `LUCID_LEDGER`, and the slash commands below.

**CSV import (REPL):**

| Command | Action |
|---------|--------|
| `/import <file.csv>` | **Guided flow**: preview detected mapping + 3 sample rows, prompt `y/N`, import on confirm |
| `/import` | Batch-import all `*.csv` in `LUCID_IMPORT_DIR` without confirmation |
| `/import preview <file.csv>` | Dry-run only — shows mapping and samples, writes nothing |
| `/import-rollback <batch_id>` | Delete all transactions from a batch and rebalance the account |
| `/import-mapping list` | List saved mapping profiles |
| `/import-mapping save <name>` | Save the last previewed mapping as a named profile (auto-matched on future imports with the same header layout) |
| `/import-mapping set-default <id>` | Mark a profile as default |

**Categorization (REPL):**

| Command | Action |
|---------|--------|
| `/cat-run` | Run the categorizer LLM on a batch of uncategorized outflows |
| `/review-categories` | Table of pending proposals + deterministic `categorize_transaction` hint |
| `/cat-accept <proposal_id> [bucket need] [line groceries]` | Apply to `transactions` and mark proposal accepted |
| `/cat-reject <proposal_id>` | Mark proposal rejected |

---

## REPL environment switches

| Variable | Effect |
|----------|--------|
| `LUCID_DB_PATH` | SQLite path; default `:memory:` (ephemeral). Use a file path to persist profiles and imports. |
| `LUCID_IMPORT_DIR` | Where `/import` looks for `*.csv`; default `data/imports`. |
| `LUCID_LEDGER` | `demo` (default): seeded demo transactions. `import`: minimal user + empty ledger for CSV-first workflows. |

---

## Tests

- [`tests/test_ingest_csv.py`](../tests/test_ingest_csv.py) — 14 tests covering:
  - Header detection (semicolon, UTF-8, encoding fallback)
  - `strip_sep_hint` utility
  - `find_header_row_index` with single `sep=;` row, 5 metadata rows, and French-language metadata
  - `detect_mapping` sign_rule disambiguation (Amount vs Debit+Credit via sample rows)
  - UBS MasterCard end-to-end format (sep=; + mixed columns)
  - Multi-metadata-row end-to-end format (5 preamble lines before real header)
  - Import insert + duplicate skip + force re-import
  - Profile save and auto-reload by header hash
  - Rollback
  - Preview
- [`tests/test_ledger_tools.py`](../tests/test_ledger_tools.py) — invalid bucket rejection, propose + apply updates `transactions`.

Run:

```bash
pytest tests/test_ingest_csv.py tests/test_ledger_tools.py -q
```

---

## Related documentation

| Document | Content |
|----------|---------|
| [REPL_README.md](../REPL_README.md) | Slash commands, env vars, CSV workflow for users |
| [CLAUDE.md](../CLAUDE.md) | Global architecture constraints (`BankingProvider`, `ingest/`, agents) |
| [docs/STAGE_1.md](STAGE_1.md) | Contracts and `BankingProvider` baseline |
| [docs/STAGE_2.md](STAGE_2.md) | Deterministic `tools/` core |

This file is the **feature reference** for CSV import and ledger-side categorization; it is intentionally **not** named after a numbered stage.

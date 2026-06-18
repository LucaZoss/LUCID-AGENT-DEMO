# LUCID AGENT — Terminal REPL

A styled, conversational terminal client for the LUCID personal finance agent.

---

## One-command launch (uv)

```bash
uv sync && uv run lucid-agent
```

That's it. `uv sync` creates an isolated virtual environment and installs
every dependency automatically. `uv run lucid-agent` starts the TUI.

On first run with no API key and no local model server, the REPL shows an
interactive provider wizard so you can enter a key or point to a local model.

---

## First-time setup

### 1 — Install uv (if you don't have it)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2 — Clone and sync

```bash
git clone <repo-url>
cd LUCID-AGENT-DEMO
uv sync                    # creates .venv + installs all runtime deps
```

### 3 — (Optional) add your LLM provider

Pick one:

```bash
# Cloud APIs
export ANTHROPIC_API_KEY=sk-ant-...   # Claude — recommended
export OPENAI_API_KEY=sk-...          # GPT-4o
export GOOGLE_API_KEY=...             # Gemini

# Also install the matching SDK extra so LiteLLM can reach it
uv sync --extra claude    # for Claude
uv sync --extra openai    # for OpenAI
```

If you skip this step the REPL detects local model servers automatically
(llama.cpp, Ollama) and falls back to an interactive wizard.

### 4 — Launch

```bash
uv run lucid-agent
```

---

## Provider options

The REPL auto-detects a provider in this order. Pass a model string to
override.

| Priority | Provider | What it checks | Override |
|---|---|---|---|
| 1 | **llama.cpp** | server at `$LLAMACPP_URL` (default `:8080`) | `uv run lucid-agent openai/<model>` |
| 2 | **Claude** | `$ANTHROPIC_API_KEY` | `uv run lucid-agent claude-sonnet-4-6` |
| 3 | **GPT-4o** | `$OPENAI_API_KEY` | `uv run lucid-agent gpt-4o` |
| 4 | **Gemini** | `$GOOGLE_API_KEY` | `uv run lucid-agent gemini/gemini-1.5-pro` |
| 5 | **Ollama** | server at `$OLLAMA_URL` (default `:11434`) | `uv run lucid-agent openai/mistral:7b-instruct` |
| 6 | **Wizard** | interactive fallback | — |

### llama.cpp

```bash
# Terminal 1 — start the server with any GGUF model
llama-server -m ~/models/mistral-7b-instruct.Q4_K_M.gguf --port 8080

# Terminal 2
uv run lucid-agent
```

### Ollama

```bash
ollama pull mistral
uv run lucid-agent
```

---

## What you'll see

```
    __    __  ________________     ___   _____________   ________
   / /   / / / / ____/  _/ __ \   /   | / ____/ ____/ | / /_  __/
  / /   / / / / /    / // / / /  / /| |/ / __/ __/ /  |/ / / /
 / /___/ /_/ / /____/ // /_/ /  / ___ / /_/ / /___/ /|  / / /
/_____/\____/\____/___/_____/  /_/  |_\____/_____/_/ |_/ /_/

────────────────────────────────────────────────────────────────
                     Personal finance assistant
              type /help for commands · /quit to exit
────────────────────────────────────────────────────────────────

                  provider: openai/phi4-mini:3.8b

› you  _
```

Banner color is a cyan-to-blue gradient. The active provider shows
below the subtitle. Type a message and press Enter.

---

## Slash commands

| Command | What it does |
|---|---|
| `/help` | Show available commands in a panel |
| `/clear` | Clear the screen — session continues, history kept |
| `/quit` | Exit cleanly |

- **Ctrl-C** while the agent is thinking → cancels that turn, stays in the REPL.
- **Ctrl-C / Ctrl-D** at the prompt → prints "Goodbye." and exits.

---

## Things to try (backtesting the agent)

The REPL starts with an in-memory demo database loaded with three months of
realistic CHF transactions — salary, rent, groceries, dining, savings
transfers. No real bank data needed.

### See your current spending

```
What does my spending look like?
```
Runs `compute_current_split` on 90 days. Returns needs / wants / savings
in CHF and percentages, grounded in the demo data.

```
Show me my top merchants this month
```
Runs `get_dashboard_summary`. Returns the top-10 merchants by spend.

```
Give me a full picture of my finances
```
Full dashboard: split ratios, top merchants, budget-vs-actual, goal progress.

### Classify a merchant

```
Is Starbucks a need or a want?
```
```
What about Coop To Go?
```
```
Is Manor a need or a want?
```
Runs `categorize_merchant` — purely deterministic, no LLM arithmetic. Good
for testing edge cases (Coop To Go → want before Coop → need).

### Savings planning — low effort

```
I want to save more but I really don't want to track every purchase.
```
Routes to `goal_intake` then `recommend_framework`. The agent should
ask about income, then suggest a plan in plain language anchored to your
actual numbers — no methodology names like "pay-yourself-first".

### Savings planning — specific target

```
I'm saving CHF 10,000 for a trip by end of December.
I'm willing to track things carefully. What's the plan?
```
Same route, different engagement level. Expect a plan with a concrete
monthly transfer amount derived from the demo spending data — not
"I recommend zero-based budgeting".

### Goal feasibility check

```
Am I on track with my savings goal?
```
Runs `get_goal_status`. If no goal is set, the agent prompts for one.
Returns required monthly savings and on-track / off-track status.

### Overspend triage

```
I went over my dining budget this week — what should I do?
```
Routes to `diagnose_overspend`. One sentence with a concrete suggested
action. Not a lecture.

---

## Run the framework-language demo

Verifies that neither response names an internal budgeting methodology
(`pay-yourself-first`, `zero-based`, `50/30/20`, …):

```bash
uv run python demo_framework_language.py
```

Output: two responses side-by-side (open-ended saver vs. CHF 10k target),
each followed by a pass / fail banner-terms check.

---

## Run the test suite

```bash
uv run pytest -q        # offline; no API key needed
```

---

## CSV import and mapping profiles

Use **`/setup`** in the REPL anytime for a concise checklist (import folder, `LUCID_DB_PATH`, `LUCID_LEDGER`, and which slash commands to run). It shows the resolved import folder and your current environment values.

Drop one or more bank **CSV** files into `data/imports/` (or set **`LUCID_IMPORT_DIR`** to another folder). The REPL auto-detects common Swiss / English column headers, deduplicates rows by a stable fingerprint, and reconciles the account balance from the sum of all transactions.

| Environment variable | Purpose |
|----------------------|---------|
| `LUCID_IMPORT_DIR` | Directory scanned for `*.csv` (default: `data/imports`) |
| `LUCID_DB_PATH` | SQLite database file path. Default is **`:memory:`** — mapping profiles and imported rows are **not** kept after exit. Set to e.g. `lucid_demo.db` to persist. |
| `LUCID_LEDGER` | `demo` (default): seed demo transactions. `import`: empty ledger + same user/account row for CSV-only workflows. |

**Slash commands**

| Command | Action |
|---------|--------|
| `/setup` | Step-by-step help for CSV import, persistence (`LUCID_DB_PATH`), and categorization commands |
| `/import` | Import every `*.csv` in the import directory (optional: `profile <uuid>`; `force` / `--force` to re-read an unchanged file) |
| `/import preview <file.csv>` | Show headers, detected column mapping, and sample rows |
| `/import-preview <file.csv>` | Same as `/import preview` |
| `/import-rollback <batch_id>` | Delete transactions from one import batch (id printed after `/import`) |
| `/import-mapping list` | List saved mapping profiles |
| `/import-mapping save <name>` | Save the mapping from the last `/import-preview` |
| `/import-mapping set-default <id>` | Mark a profile as default for the user |
| `/cat-run` | Run the **ledger categorization** LLM (separate from the budgeting agent) to queue proposals |
| `/review-categories` | List pending bucket/line proposals + deterministic `need/want/savings` hint |
| `/cat-accept <proposal_id> [bucket need] [line groceries]` | Apply a proposal (optional overrides) |
| `/cat-reject <proposal_id>` | Reject a proposal |

Non-interactive preview:

```bash
uv run python -m ingest.cli path/to/export.csv
```

---

## Session persistence

By default the REPL uses **`LUCID_DB_PATH=:memory:`** (or unset). Mapping profiles, import batches, and CSV-imported transactions disappear when you exit. Type **`/setup`** in the REPL for a reminder and example shell commands.

To persist across restarts, set a file path:

```bash
export LUCID_DB_PATH=lucid_demo.db
uv run lucid-agent
```

You can still override in code, but the environment variable is the supported switch (see [orchestrator/repl.py](orchestrator/repl.py)).

---

## Project layout (reference)

```
LUCID-AGENT-DEMO/
├── orchestrator/
│   ├── repl.py            ← TUI entry point
│   ├── router.py          ← route → skill → tool loop → response
│   └── context_assembler.py
├── skills/
│   ├── skill_loader.py    ← two-stage manifest + full-load
│   ├── goal_intake/
│   ├── recommend_framework/
│   ├── build_budget/
│   └── diagnose_overspend/
├── llm/
│   ├── provider.py        ← LLMProvider interface
│   ├── config.py          ← auto-detect + wizard
│   └── adapters/litellm_adapter.py
├── ingest/                ← deterministic CSV import + mapping profiles
├── agents/                ← ledger categorization LLM loop (not the budgeting router)
├── tools/                 ← deterministic tools (no LLM)
├── bank/                  ← BankingProvider + SimulatedBank
├── db/db_schema.py
└── pyproject.toml         ← entry point: lucid-agent
```

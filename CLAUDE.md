# Personal Finance Agent

## What this is
An LLM-provider-agnostic personal finance agent. It helps a user define a
budget that meets their financial goals, notifies them after transactions, and
feeds a dashboard. The demo runs against a **simulated bank** (real SIX / Swiss
open-banking comes later behind the same interface). Currency is **CHF**;
amounts are negative for outflows.

---

## Architecture (do not violate)

- **Bank access** goes through the `BankingProvider` interface only. Never
  import a concrete bank (`SimulatedBank` / `SixBank`) anywhere except the
  config/wiring layer. Swapping the simulator for SIX must be a one-line change.
- **LLM access** goes through the `LLMProvider` interface only. Never import a
  vendor SDK (`anthropic`, `openai`, etc.) outside its adapter in
  `llm/adapters/`. Default adapter wraps LiteLLM for provider agnosticism.
- **Money math is deterministic** and lives in `tools/`. The LLM NEVER does
  arithmetic — it calls tools. If the model is computing a ratio or a required
  monthly saving, that is a bug.
- **Tools vs Skills:**
  - *Tools* = pure deterministic Python functions (categorize, compute, fetch).
  - *Skills* (SKILL.md) = LLM judgment / multi-step procedures (goal intake,
    framework choice, explanation).
- **CSV ingest** (`ingest/`) = deterministic parsing, column auto-detect, mapping
  profiles, import batches, dedupe fingerprints, and balance reconciliation. Not
  a second `BankingProvider` — it writes the same SQLite `transactions` rows the
  demo seed uses.
- **Ledger categorization agent** (`agents/ledger_categorizer.py`) = a **second**
  small LLM loop with its own tools (`propose_spending_bucket`, `propose_line_category`).
  It does **not** use `orchestrator/router.py` or budgeting skills. Proposals land
  in `category_proposals` until the user applies them via the REPL (`/cat-accept`).

## How the router uses SKILL.md (two-stage / lazy loading)

The agent loop mirrors how Claude's own skill system works: a cheap manifest
scan first, full instructions loaded only on demand.

1. **Discover** — `list_skills()` scans the `skills/` directory and returns just
   `{name, description}` for each skill, read from the YAML frontmatter of each
   `skills/<name>/SKILL.md`. This is the cheap manifest. Cache it (SKILL.md
   files don't change per request).
2. **Route** — the router LLM is given the list of `{name, description}` plus
   the user request and picks the relevant skill(s) — same matching logic as an
   `<available_skills>` block: descriptions matched against the task.
3. **Load** — only after a skill is picked does `read_skill(name)` load the FULL
   SKILL.md into context. This keeps the router's context small until it commits
   to a path.
4. **Iterate** — the SKILL.md content tells the agent what to do next: which
   tools/scripts to call, in what order, what formats to expect. Feed that back
   into context and let it proceed (it may call `bash`, `view`, other tools, or
   read nested resource files the SKILL.md points to).

Key points:
- Two-stage loading: cheap manifest scan → full read only on demand. Never load
  every skill's full instructions at once.
- Treat SKILL.md as a **router, not just docs**: it is executable guidance that
  chains the agent into a multi-step plan (which sub-tools/scripts to invoke).
- **Frontmatter contract** — standardize fields so matching is reliable:
  `name`, `description`, `triggers`, `tools_required`, `outputs`.
- Re-read the full SKILL.md when iterating, in case its scripts/resources
  changed; only the manifest is cached.

---

## First Python tools the agent needs (deterministic, no LLM)

Build and unit-test these BEFORE wiring the LLM in:

- `categorize_transaction(txn) -> "need" | "want" | "savings"` — rules + a
  merchant lookup table first; LLM fallback only for ambiguous merchants.
- `compute_split(income, transactions) -> {needs_pct, wants_pct, savings_pct}`
  — the actual needs/wants/savings ratios from real transactions. Pure math.
- `compute_goal_feasibility(goal, income, current_savings)
  -> {required_monthly, on_track: bool}` — pure math.
- `check_budget(txn) -> breach | None` — the deterministic rule the event loop
  calls on every new transaction (most transactions need only this, NOT the LLM).
- `build_dashboard_payload(...)` — assembles chart data. Lock this shape early;
  it is the contract between the deterministic core and the UI.

Rule: every new tool ships with a pytest unit test.

---

## Budgeting strategy & how to route between techniques

The needs/wants/savings split is the categorization primitive underneath all
frameworks — it is not itself a framework. There is no single best framework;
the right one depends on the user's goal type and engagement appetite. The
agent's job is to pick the framework, then call tools to compute it.

Frameworks:
- **50/30/20** (needs/wants/savings) — simple, works for open-ended "save
  money" goals. Percentages are a US guideline; make ratios CONFIGURABLE. In
  Switzerland, rent + health-insurance premiums often push "needs" past 50% —
  report the user's actual ratio neutrally, never call it "wrong".
- **Zero-based (YNAB-style)** — every franc gets a job; each goal funded as an
  explicit category. Best for SPECIFIC targets. Higher engagement required.
- **Pay-yourself-first** — skim savings off the top, spend the rest freely.
  Lowest friction; best for the hands-off open-ended saver.

Routing table:

| User goal | Framework |
|---|---|
| Open-ended ("save money") | Pay-yourself-first or 50/30/20 |
| Specific target + date ("CHF 10k by June") | Zero-based, goal as a funded category |
| Wants control / will track | Zero-based |
| Wants minimal effort | Pay-yourself-first |

Conversation flow:
```
user goal
  -> [skill: goal_intake]        => structured_goal {type, amount?, date?, engagement, income, essentials_pct}
  -> [skill: recommend_framework] => 50/30/20 | zero-based | pay-first
  -> [tool: get_transactions] -> [tool: categorize] -> [tool: compute_split]
  -> [skill: build_budget]       => allocations + plain-language rationale
  -> [tool: build_dashboard_payload] => dashboard renders
```

Critical rule for the OPEN-ENDED case: when a user just says "save money" with
no target, DO NOT invent a target. Either run pay-yourself-first (skim a
sustainable % off the top) or surface their current actual ratios and ask what
feels right. The dashboard then tracks progress against THEIR baseline, not an
arbitrary number. Always ground recommendations in real computed numbers
(`compute_split` on last ~90 days) before advising — never assume ratios.

---

## Notifications flow

Delivery goes through a `Notifier` interface (same swap pattern as
`BankingProvider` / `LLMProvider`). Demo target is **Telegram** (free, instant
setup via @BotFather, native inline buttons). `ConsoleNotifier` for terminal
testing; `TelegramNotifier` for the demo. No other chat app is simulated.

Tier transactions — do NOT push on every one (noise kills the channel):
- **Silent** (dashboard only, no push): normal in-budget spending. The majority.
- **Informational** (gentle, BATCHABLE into a digest): approaching a limit,
  e.g. "80% of dining used". Rolled into a morning / weekly digest.
- **Actionable** (immediate push): budget breach, goal off-track, unusual/large
  txn, likely duplicate. Only this tier carries an explanation + a next step.

Mapping to architecture:
- Silent + Informational tiers = pure `check_budget` output. Deterministic, no
  LLM. Dashboard update + maybe a queued digest line.
- Actionable tier escalates to the `diagnose_overspend` skill, which turns the
  deterministic breach into ONE human sentence with an offered action
  (e.g. "Dining's over for the month — pull CHF 30 from buffer, or tighten next
  week?"). Render the offered actions as Telegram inline buttons.

Rules:
- Never notify about something the user can't act on. "Spent CHF 40 at Coop" is
  useless; "that puts groceries at 95% with 10 days left" is actionable.
- Frequency cap (e.g. max 2–3 actionable pushes/day) + quiet hours (no overnight
  pushes). This is deterministic config, NOT agent logic.
- Actionable notifications deep-link into chat with context preloaded rather
  than being independently smart. A button press arrives as a Telegram webhook
  → routed into the agent with the originating notification's context.

## Memory & state (four distinct layers — do not conflate)

Principle: **structured state lives in the DB and is authoritative. LLM context
is a derived, lossy view assembled fresh per request.** Never treat conversation
history as the source of truth for facts. If the goal is "CHF 10k", that number
is a DB row, not a sentence the model must remember.

1. **Durable user facts (profile/state)** — `structured_goal`, chosen framework,
   budget, notification prefs, quiet hours. Authoritative, structured → DB.
   Output of onboarding; read by deterministic tools. Treat as app state.
2. **Financial history (ledger)** — every transaction, computed splits over
   time, goal-progress snapshots. Structured → DB. Queried with SQL/pandas,
   NEVER embeddings. Feeds the dashboard and `compute_*` tools.
3. **Conversational memory (dialogue)** — layered, not "stuff everything in":
   - short-term: recent turns verbatim in context
   - summarized: older turns compressed into a running summary
   - retrieved (OPTIONAL, deferred for demo): embed past chat/notes, pull only
     relevant chunks. This is the ONLY legitimate place for RAG — recall over
     conversations/notes, never over transactions.
4. **Agent-learned preferences (soft memory)** — e.g. "dismissed dining alert 3×
   → suppress". Store as STRUCTURED, reviewable rows in a `preferences` table,
   not free text the LLM mutates at will. GUARDRAIL: never let learned
   suppression silence a genuine overspending/goal-risk warning — safety alerts
   are not suppressible.

Per-turn context assembly (rebuilt every turn from durable stores):
```
system prompt
+ user profile (DB: goal, framework, prefs)            <- structured facts
+ current financial snapshot (tools run FRESH: this month's split, goal progress)
+ running conversation summary (older turns, compressed)
+ last N turns verbatim
+ [retrieved relevant notes, if RAG enabled — deferred]
+ current user message
```
Tools run fresh each turn so the agent reasons over today's numbers, never a
stale remembered figure.

State changes are DETERMINISTIC transitions, not LLM whims: when the user agrees
to "pull CHF 30 from buffer", the LLM decides THAT it happens; a tool performs
and persists the mutation to the DB. Same discipline as the money math.

Notification replies carry minimal state: store pending actionable notifications
as small rows ("notif_123: offered buffer-pull CHF 30, awaiting reply") and
resolve on reply — don't reconstruct intent from conversation memory.

Demo scope: DB profile + running summary + last N turns is enough. RAG-based
long-term recall is DEFERRED unless explicitly needed.

---

## Conventions
- Type hints everywhere; dataclasses for contracts (`Transaction`, `Account`,
  `StructuredGoal`, `Budget`).
- Tests with pytest in `tests/`; run `pytest -q`.
- Update this file when the architecture changes.

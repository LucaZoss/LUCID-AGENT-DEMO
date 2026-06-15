# Stage 2 — Deterministic Tools & Simulator Retuning

## What this covers

Phase 2 from CLAUDE.md: the five deterministic tool functions that form the computational core of the agent, plus a retuning of the SimulatedBank to produce a realistic Swiss spending profile.

The LLM is still not wired. Every calculation here is pure deterministic Python — the LLM will call these tools later, but it will never replicate their math.

---

## Files added / changed

```
LUCID-AGENT-DEMO/
├── bank/
│   └── simulated.py          # CHANGED — spending profile retuned
├── tools/
│   ├── __init__.py           # re-exports all public symbols
│   ├── categorize.py         # categorize_transaction
│   ├── split.py              # compute_split + SplitResult
│   ├── feasibility.py        # compute_goal_feasibility + FeasibilityResult
│   ├── budget.py             # check_budget + BudgetBreach
│   └── dashboard.py          # build_dashboard_payload + DashboardPayload
└── tests/
    └── test_tools.py         # 60 unit tests (73 total across the suite)
```

---

## SimulatedBank retuning (`bank/simulated.py`)

The Stage 1 simulator produced an implausibly frugal profile (43.8% needs / 11.5% wants / 44.7% savings). A 44.7% savings rate makes the demo user look like they don't need budgeting help. The following changes were made to reach a realistic Zürich profile.

### Parameter changes

| Parameter | Before | After | Reason |
|---|---|---|---|
| Monthly salary | CHF 7 100–7 300 | CHF 6 600–6 900 | More realistic mid-level salary |
| Rent (DOM 1) | CHF 1 800 | CHF 2 200 | Zürich market rate |
| Home internet (DOM 10) | absent | CHF 69 (Quickline AG) | Fixed utility |
| Electricity (DOM 28) | absent | CHF 72–88 (EWZ) | Fixed utility |
| Streaming (DOM 2) | Netflix + Spotify | + Disney+ (CHF 9.90) | Realistic subscription stack |
| Groceries Monday | 85%, CHF 68–145 | 90%, CHF 100–185 | More realistic weekly basket |
| Saturday grocery top-up | absent | 48%, CHF 35–65 | Weekend market run |
| Thursday midweek top-up | 35%, CHF 18–52 | 55%, CHF 28–70 | More frequent restocking |
| Coffee weekdays | 60% daily | 70% daily | Coffee culture |
| Coffee weekends | absent | 35% daily | Weekend café visits |
| Dining Fri–Sun | 55%, CHF 28–95 | 73%, CHF 48–120 | More realistic going-out spend |
| Extra Saturday dining | absent | 22% probability | Dinner + late-night visit |
| Weekday lunch | 20%, CHF 12–28 | 42%, CHF 15–32 | Office-lunch habit |
| Bars / nightlife Fri–Sat | absent | 27%, CHF 38–88 | `_BARS` list added |
| Clothing | 4%, CHF 45–195 | 6%, CHF 60–220 | |
| Electronics | 2.5%, CHF 35–320 | 3.5%, CHF 45–350 | |
| Entertainment | 12%, CHF 18–85 | 22%, CHF 22–95 | |
| Pharmacy | 6% | 7% | |
| SBB extra tickets | 12% | 15% | |

### Confirmed 90-day ratios (seed=42, reference date 2026-06-15)

```
Income:  CHF 20,214.29  |  Transactions: 209
Needs:   CHF 11,690.52  →  57.8%   (target: 50–60%)  ✓
Wants:   CHF  6,381.96  →  31.6%   (target: 25–35%)  ✓
Savings: CHF  2,141.81  →  10.6%   (target: 10–20%)  ✓
```

All three buckets land in range. The profile now represents a user who earns a solid Zürich salary, carries realistic fixed costs, and has moderate-but-real discretionary spending — someone who genuinely benefits from budgeting guidance.

---

## Tool 1 — `categorize_transaction` (`tools/categorize.py`)

### Signature

```python
def categorize_transaction(txn: Transaction) -> str
# returns: "need" | "want" | "savings"
# raises:  ValueError if txn.amount >= 0 (income is not categorizable)
```

### How it works

A 49-entry ordered `_RULES` list of `(pattern, category)` tuples is scanned top-to-bottom. The first match on `merchant.lower()` wins. Unknown merchants default to `"want"`.

**Critical ordering guarantee:** `"want"` patterns are checked before `"need"` patterns where merchants overlap. This resolves ambiguity correctly:

| Merchant | Wins on | Result |
|---|---|---|
| `"Migros Restaurant"` | `"restaurant"` (want) fires before `"migros"` (need) | `"want"` |
| `"Coop To Go"` | `"to go"` (want) fires before `"coop"` (need) | `"want"` |
| `"Coop"` | `"coop"` (need) | `"need"` |

**Rule order:** savings → wants (specific patterns first) → needs → default `"want"`.

### Key rule groups

| Category | Pattern examples |
|---|---|
| `savings` | `viac`, `frankly`, `swissquote` |
| `want` | `starbucks`, `to go`, `restaurant`, `café`, `bar`, `netflix`, `spotify`, `zara`, `zalando`, `digitec`, `gym`, `fitnesspark` |
| `need` | `coop`, `migros`, `aldi`, `denner`, `sbb`, `zvv`, `immobilien`, `apotheke`, `krankenversicherung`, `swisscom`, `quickline`, `ewz` |

---

## Tool 2 — `compute_split` (`tools/split.py`)

### Signature

```python
def compute_split(transactions: list[Transaction]) -> SplitResult
# raises: ValueError if no income transactions found
```

### `SplitResult` dataclass

| Field | Type | Notes |
|---|---|---|
| `income_chf` | `float` | Sum of all positive-amount transactions |
| `needs_chf` | `float` | Absolute spend in `"need"` category |
| `wants_chf` | `float` | Absolute spend in `"want"` category |
| `explicit_savings_chf` | `float` | Transactions pre-categorized as `"savings"` (e.g. VIAC transfers) |
| `residual_savings_chf` | `float` | `income − needs − wants − explicit_savings` — can be negative (overspending) |
| `savings_chf` | `float` | `explicit_savings + max(0, residual)` — clamped to zero if overdrawn |
| `needs_pct` | `float` | `needs / income × 100` |
| `wants_pct` | `float` | `wants / income × 100` |
| `savings_pct` | `float` | `savings_chf / income × 100` — zero when overdrawn |

### Behavior rules

- Uses `txn.category` if set; falls back to `categorize_transaction(txn)` for `None`.
- Negative residual (overspending) is stored verbatim in `residual_savings_chf`; `savings_chf` and `savings_pct` are clamped to zero.
- Percentages are computed from gross income, not from each other, so they always sum to 100% only when nothing is overspent.

---

## Tool 3 — `compute_goal_feasibility` (`tools/feasibility.py`)

### Signature

```python
def compute_goal_feasibility(
    goal: StructuredGoal,
    monthly_income: float,
    current_savings: float,
    reference_date: date | None = None,   # defaults to today
) -> FeasibilityResult
# raises: ValueError if monthly_income <= 0
```

### `FeasibilityResult` dataclass

| Field | Type | Notes |
|---|---|---|
| `goal_type` | `str` | `"open"` or `"target"` |
| `required_monthly_chf` | `float` | How much to save per month to hit the goal; `float("inf")` if deadline passed with remaining balance |
| `on_track` | `bool` | `True` if `required_monthly <= monthly_income` |
| `months_remaining` | `float` | Fractional months to deadline; `0.0` for open goals and past deadlines |
| `still_needed_chf` | `float` | `goal.amount − current_savings`; `0.0` for open goals |
| `suggested_rate_pct` | `float` | `required_monthly / monthly_income × 100` |

### Routing logic

| Condition | Behavior |
|---|---|
| `goal_type == "open"` | `required_monthly = income × 10%`; `on_track = True`; `months_remaining = 0` |
| Target goal, deadline not yet passed | `months = days_left / 30.4375`; `required = still_needed / months` |
| Target goal, deadline passed, still owed | `required = float("inf")`; `on_track = False`; `months_remaining = 0.0` |

Calendar math uses `_DAYS_PER_MONTH = 30.4375` (365.25 / 12) throughout.

---

## Tool 4 — `check_budget` (`tools/budget.py`)

### Signature

```python
def check_budget(
    txn: Transaction,
    budget: Budget,
    period_transactions: list[Transaction],  # must NOT include txn itself
) -> BudgetBreach | None
```

Returns `None` for all of: income transactions, categories absent from `budget.allocations`, and transactions that land at or below the limit. Returns a `BudgetBreach` only when the category total after adding `txn` **exceeds** the limit.

### `BudgetBreach` dataclass

| Field | Type | Notes |
|---|---|---|
| `category` | `str` | Which budget line was breached |
| `merchant` | `str` | Triggering merchant name |
| `txn_amount_chf` | `float` | Absolute value of the incoming transaction |
| `period_spent_chf` | `float` | Category total after adding txn |
| `limit_chf` | `float` | The allocation from `budget.allocations` |
| `overage_chf` | `float` | `period_spent − limit` |
| `overage_pct` | `float` | `overage / limit × 100` |

### Key rule

`total_after <= limit` is **not** a breach. Exactly at the limit is acceptable; only strictly over triggers a breach. This is deliberate: the user agreed to a limit, hitting it exactly honors the budget.

### Role in the event loop

`check_budget` is called on every incoming transaction. The vast majority return `None` (silent path — dashboard-only update, no LLM involved). Only a returned `BudgetBreach` escalates to the `diagnose_overspend` skill (Phase 3), which converts it into a human sentence with an offered action and a Telegram notification.

---

## Tool 5 — `build_dashboard_payload` (`tools/dashboard.py`)

### Signature

```python
def build_dashboard_payload(
    period: str,
    transactions: list[Transaction],
    budget: Budget | None = None,
    goal: StructuredGoal | None = None,
    current_savings: float = 0.0,
    monthly_income: float | None = None,
) -> DashboardPayload
```

### `DashboardPayload` dataclass

| Field | Type | Notes |
|---|---|---|
| `period` | `str` | e.g. `"2026-06"` |
| `generated_at` | `datetime` | UTC timestamp of assembly |
| `split` | `SplitResult` | Full needs/wants/savings breakdown |
| `top_merchants` | `list[MerchantSummary]` | Top-10 by absolute spend, descending |
| `category_breakdown` | `list[CategoryLine]` | One row each for need / want / savings |
| `budget_vs_actual` | `list[BudgetVsActualLine] \| None` | `None` when no budget supplied |
| `goal_progress` | `dict \| None` | `None` when no goal supplied |
| `income_chf` | `float` | Mirrors `split.income_chf` |
| `total_outflow_chf` | `float` | `needs + wants + explicit_savings` |
| `net_chf` | `float` | `income − total_outflow` |

### Sub-shapes

**`MerchantSummary`** — `merchant`, `total_chf`, `count`, `category`

**`CategoryLine`** — `category`, `total_chf`, `pct_of_income`

**`BudgetVsActualLine`** — `category`, `budget_chf`, `actual_chf`, `pct_used`, `over_budget: bool`

**`goal_progress` dict keys** — `goal_type`, `target_chf`, `target_date`, `saved_chf`, `pct_complete`, `required_monthly_chf`, `on_track`, `months_remaining`

### Important usage note

`budget.allocations` should match the transaction window's time period. If you pass 90 days of transactions but monthly allocation limits, the comparison is misleading. This is the caller's responsibility — the tool does not enforce period alignment.

---

## Tests (`tests/test_tools.py`)

60 tests, all green. Combined with the 13 bank tests from Stage 1: **73 tests, 0 failures**.

```bash
pytest -q
# 73 passed in 0.05s
```

All test fixtures use hand-built transaction lists (`_simple_txns`, `_base_txns`) — never live simulator output. This keeps tests deterministic and independent of simulator tuning.

### Coverage by tool

| Class | Tests | What is covered |
|---|---|---|
| `TestCategorizeTransaction` | 18 | All grocery/health/transport/dining/savings merchants; ordering edge cases (Coop To Go, Migros Restaurant); default-to-want; positive-amount raise; pre-set category ignored |
| `TestComputeSplit` | 12 | Income summing; needs/wants CHF; residual; pcts (pinned literals); preset category respected; fallback categorizer; explicit savings; no-income raise; overspending (negative residual, savings_pct clamped to 0) |
| `TestComputeGoalFeasibility` | 9 | Target goal monthly rate; on-track/off-track; partial savings reduce required (pinned literals); open goal 10% suggestion; months remaining; deadline-passed → `inf`; zero-income raise |
| `TestCheckBudget` | 9 | Under limit; over limit; overage CHF and pct; income ignored; missing category key; categorizer fallback; period transactions counted; exactly-at-limit → None |
| `TestBuildDashboardPayload` | 12 | Return type + pinned split values; income; net CHF (pinned literal); merchant sort; top-10 cap; three category rows; budget_vs_actual populated/None; goal_progress populated/None; period stored |

### Pinned literal values

These were hand-computed before being written into tests — not derived from running the code:

| Test | Input | Expected |
|---|---|---|
| `test_wants_pct_pinned` | wants=250, income=6000 | `4.2%` |
| `test_savings_pct_pinned` | residual=3550, income=6000 | `59.2%` |
| `test_overspending_negative_residual` | income=1000, outflow=1200 | `residual=−200`, `savings_chf=0`, `savings_pct=0%` |
| `test_net_is_income_minus_outflow` | income=7200, outflow=2829 | `net=4371.0` |
| `test_returns_dashboard_payload` | needs=2600, wants=229 | pinned split fields |
| `test_partial_savings_reduce_required` | saved=5000, goal=10000, months=12 | `still_needed=5000`, `required≈417` |
| `test_deadline_passed_returns_inf` | target=2025-01-01, ref=2026-06-01 | `required=inf`, `on_track=False`, `months=0` |
| `test_no_breach_exactly_at_limit` | period=−3400, txn=−100, limit=3500 | `None` (no breach) |

---

## Architecture rules enforced

- **No LLM in any tool.** All five functions are pure Python with no external calls. The LLM will call them; it will never replicate their math.
- **Money math is deterministic.** `compute_split`, `compute_goal_feasibility`, and `check_budget` are the canonical sources for all ratio and feasibility figures. If the model is computing a percentage, that is a bug.
- **`check_budget` is the hot path.** It runs on every transaction, returns `None` for the vast majority, and never touches the LLM. Only a returned `BudgetBreach` escalates.
- **`build_dashboard_payload` shape is frozen.** The UI renders exactly what is in `DashboardPayload`. Adding or renaming a field is a breaking change and requires updating the frontend contract at the same time.

---

## What is NOT here yet (Phase 3+)

- `llm/` — `LLMProvider` interface and adapters (LiteLLM wrapper)
- `skills/` — `goal_intake`, `recommend_framework`, `build_budget`, `diagnose_overspend`
- `notifier/` — `Notifier` interface, `ConsoleNotifier`, `TelegramNotifier`
- The agent loop: routing → skill loading → tool calls → DB persistence
- DB layer: `StructuredGoal`, `Budget`, `preferences` table persistence
- Conversation memory: running summary + last-N-turns context assembly

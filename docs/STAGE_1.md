# Stage 1 — Scaffold & Bank Simulator

## What this covers

Phase 0 (contracts + interfaces) and Phase 1 (simulated bank) from CLAUDE.md.
The LLM is not wired yet. Everything here is deterministic Python with no external dependencies.

---

## Files added

```
LUCID-AGENT-DEMO/
├── contracts.py          # shared dataclass contracts
├── pyproject.toml        # project config + pytest path
├── demo_bank.py          # runnable demo
├── bank/
│   ├── __init__.py
│   ├── provider.py       # BankingProvider interface (ABC)
│   └── simulated.py      # SimulatedBank implementation
└── tests/
    ├── __init__.py
    └── test_bank.py      # 13 unit tests
```

Pre-existing files (`db/db_schema.py`, `orchestrator/context_assembler.py`) are untouched.

---

## Dataclass contracts (`contracts.py`)

Four dataclasses define the shapes that cross layer boundaries — bank → tools → LLM → dashboard. Changing these is a breaking change.

### `Transaction`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Unique per transaction |
| `account_id` | `str` | FK to Account |
| `amount` | `float` | **Negative = outflow**, positive = inflow |
| `currency` | `str` | Always `"CHF"` in the demo |
| `merchant` | `str` | Raw merchant name; fed to the categorizer |
| `category` | `str \| None` | `"need"` / `"want"` / `"savings"` — set by the categorizer tool, not by the bank |
| `ts` | `datetime` | Timezone-aware UTC |

### `Account`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | |
| `user_id` | `str` | |
| `name` | `str` | e.g. `"Privatkonto"` |
| `balance` | `float` | Mutable — updated by `force_transaction` |
| `currency` | `str` | Default `"CHF"` |

### `StructuredGoal`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | |
| `user_id` | `str` | |
| `goal_type` | `str` | `"open"` or `"target"` |
| `engagement` | `str` | `"low"` or `"high"` — routes framework selection |
| `amount` | `float \| None` | Target amount; `None` for open goals |
| `target_date` | `date \| None` | Deadline; `None` for open goals |
| `framework` | `str \| None` | `"50_30_20"` / `"zero_based"` / `"pay_first"` |
| `active` | `bool` | Default `True` |

### `Budget`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | |
| `user_id` | `str` | |
| `allocations` | `dict[str, float]` | e.g. `{"groceries": 600, "dining": 200}` |
| `target_ratios` | `dict[str, float]` | e.g. `{"needs": 0.55, "wants": 0.25, "savings": 0.20}` |
| `period` | `str` | e.g. `"2026-06"` (monthly) |

---

## `BankingProvider` interface (`bank/provider.py`)

```python
class BankingProvider(ABC):
    def get_accounts(self) -> list[Account]: ...
    def get_transactions(self, account_id: str, days: int = 90) -> list[Transaction]: ...
    def register_callback(self, cb: Callable[[Transaction], None]) -> None: ...
```

**Architecture rule:** nothing outside `bank/` ever imports `SimulatedBank` or any future concrete provider directly. Swapping the simulator for real SIX open-banking is a one-line change at the wiring layer.

---

## `SimulatedBank` (`bank/simulated.py`)

### Constructor

```python
SimulatedBank(user_id: str, seed: int = 42)
```

- Creates one `Privatkonto` account in CHF.
- Calls `_generate_history(days=90)` using a seeded `random.Random` — same seed → identical transaction list every run.
- Settles the account balance: `BASE_BALANCE (3 000 CHF) + Σ(all generated amounts)`.

### `BankingProvider` methods

| Method | Behaviour |
|---|---|
| `get_accounts()` | Returns the single `[Account]` with current balance |
| `get_transactions(account_id, days=90)` | Filters history to the last N calendar days from call-time |
| `register_callback(cb)` | Appends `cb` to the listener list; multiple callbacks all fire in order |

### Extra public methods (simulator-only)

| Method | Behaviour |
|---|---|
| `force_transaction(txn)` | Appends `txn` to history, updates account balance, fires all callbacks immediately |
| `replay_history()` | Emits every historical transaction in chronological order via all registered callbacks |

### History generation

90 days of realistic CHF spending for a Zürich-based user, generated entirely from the seeded RNG:

| Pattern | Schedule | Example merchants |
|---|---|---|
| Salary | 25th of month (~CHF 7 200) | Arbeitgeber AG Zürich |
| Rent | 1st of month (CHF 1 800) | Immobilien Zürich AG |
| Health insurance | 1st of month (~CHF 410) | CSS, Swica, Helsana |
| Gym | 5th of month (CHF 89) | Fitnesspark AG |
| Phone | 15th of month (CHF 49) | Swisscom, Sunrise, Salt |
| SBB Halbtax | 15th of month (CHF 87) | SBB CFF FFS |
| Streaming | 2nd of month (CHF 30.85) | Netflix, Spotify |
| Groceries | Weekly Monday + Thursday top-up | Coop, Migros, Aldi, Denner |
| Coffee | Weekdays, 60% daily probability | Starbucks, Sprüngli, Volg |
| Dining out | Fri–Sun 55%, weekday lunch 20% | Tibits, Zeughauskeller, Les Halles |
| SBB tickets | Weekdays, 12% daily probability | SBB CFF FFS |
| Clothing | ~4% daily probability | Zara, H&M, Manor, Zalando |
| Pharmacy | ~6% daily probability | Amavita, Zur Rose |
| Electronics | ~2.5% daily probability | Digitec, Interdiscount, Amazon |
| Entertainment | Fri–Sun 12% probability | Halle 622, Moods Jazz Club |

Categories (`"need"` / `"want"`) are pre-set on generated transactions so the tools layer has clean data for tests before the categorizer tool is built. Salary is left `category=None` — it is income, not spending, and the categorizer won't touch it.

### Typical 90-day output (seed=42, today=2026-06-15)

```
131 transactions  |  Income: +21,687.04 CHF  |  Outflow: -11,996.53 CHF
Current balance: 12,690.51 CHF
```

---

## Tests (`tests/test_bank.py`)

13 tests, all green (`pytest -q`).

| Test | What it verifies |
|---|---|
| `test_generates_at_least_100_transactions` | History is non-trivially populated |
| `test_all_transactions_are_chf` | Currency field is always `"CHF"` |
| `test_history_is_chronological` | `get_transactions` returns sorted order |
| `test_seeded_output_is_reproducible` | Same seed → same amounts and merchants |
| `test_balance_reflects_history` | Balance = BASE + Σ(all generated amounts) |
| `test_callback_fires_on_force_transaction` | Single callback receives the injected txn |
| `test_multiple_callbacks_all_fire` | All registered callbacks fire in order |
| `test_replay_history_fires_all_callbacks` | Replay emits exactly as many events as `_history` |
| `test_replay_history_is_chronological` | Replay order is chronological |
| `test_force_transaction_updates_balance` | Balance decremented by forced outflow |
| `test_force_transaction_appended_to_history` | History grows by 1 after force |
| `test_returns_one_account` | Exactly one account per user |
| `test_account_currency_is_chf` | Account currency is `"CHF"` |

Run with:

```bash
pytest -q
```

---

## Demo

```bash
python demo_bank.py
# or with a custom manual transaction:
python demo_bank.py --force-merchant "Migros" --force-amount -88.50
```

Output shows all 90-day transactions, an income/outflow summary, and the callback firing for the manually injected transaction.

---

## What is NOT here yet (Phase 2+)

- `tools/` — `categorize_transaction`, `compute_split`, `compute_goal_feasibility`, `check_budget`, `build_dashboard_payload`
- `llm/` — `LLMProvider` interface and adapters
- `skills/` — `goal_intake`, `recommend_framework`, `build_budget`, `diagnose_overspend`
- `notifier/` — `Notifier` interface, `ConsoleNotifier`, `TelegramNotifier`
- The agent loop that ties everything together

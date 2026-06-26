---
type: Dataset
title: Simulated Bank
description: SimulatedBank demo provider vs DBBankingProvider — swap via BankingProvider interface.
resource: bank/simulated.py
tags: [dataset, bank, demo]
timestamp: 2026-06-26T12:00:00Z
---

# Simulated Bank

## Source of truth

- [bank/provider.py](../../bank/provider.py) — `BankingProvider` ABC
- [bank/simulated.py](../../bank/simulated.py) — `SimulatedBank`
- [bank/db_provider.py](../../bank/db_provider.py) — `DBBankingProvider`
- [demo_bank.py](../../demo_bank.py) — standalone Phase 1 demo

## What it does

Demo replays a scripted transaction stream via `SimulatedBank`. Production path reads from SQLite via `DBBankingProvider`. Real SIX Swiss open-banking will implement the same interface later.

## BankingProvider contract

Implementations must provide account and transaction access without leaking provider details to tools or agents.

## Swap pattern

```python
# orchestrator/startup.py only
from bank.simulated import SimulatedBank      # demo seed
from bank.db_provider import DBBankingProvider  # CSV / persisted ledger
```

Swapping simulator for SIX must be a **one-line wiring change** in startup.

## LUCID_LEDGER modes

| Value | Behavior |
|-------|----------|
| `demo` (default) | Seed demo transactions via SimulatedBank |
| `import` | Empty ledger; CSV-only workflow |

## Rules for coding agents

- Never import `SimulatedBank` outside wiring layer — see [conventions/imports-and-wiring.md](../conventions/imports-and-wiring.md).
- `ingest/` writes to DB directly; it is not a bank provider.

## Related pages

- [architecture/layer-rules.md](../architecture/layer-rules.md)
- [datasets/csv-import.md](csv-import.md)
- [tables/transactions.md](../tables/transactions.md)

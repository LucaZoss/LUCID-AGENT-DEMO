---
type: Convention
title: Imports and Wiring
description: Concrete bank and LLM adapters are allowed only in config, startup, and demo wiring layers.
resource: orchestrator/startup.py
tags: [conventions, imports, wiring]
timestamp: 2026-06-26T12:00:00Z
---

# Imports and Wiring

## Source of truth

- [orchestrator/startup.py](../../orchestrator/startup.py) — main wiring point
- [orchestrator/repl.py](../../orchestrator/repl.py) — CLI entry
- [llm/config.py](../../llm/config.py) — LLM adapter selection
- [demo_bank.py](../../demo_bank.py) — standalone demo (allowed to import SimulatedBank)

## What it does

Interfaces isolate swappable implementations. Coding agents must not leak concrete providers into business logic.

## Allowed import map

| Concrete import | Allowed in |
|-----------------|------------|
| `SimulatedBank` | `orchestrator/startup.py`, `demo_bank.py`, `tests/` |
| `DBBankingProvider` | `orchestrator/startup.py`, `tests/` |
| `LiteLLMAdapter` | `llm/config.py`, `llm/adapters/` |
| `anthropic`, `openai`, etc. | `llm/adapters/` only |

## Forbidden patterns

```python
# BAD — in tools/split.py or agents/ledger_categorizer.py
from bank.simulated import SimulatedBank

# BAD — in orchestrator/router.py
import anthropic
```

## Correct patterns

```python
# GOOD — depend on interface
from bank.provider import BankingProvider

# GOOD — wiring layer picks implementation
from bank.simulated import SimulatedBank  # only in startup.py
```

## Wiring checklist

When adding a new provider:

1. Implement the interface (`BankingProvider` or `LLMProvider`).
2. Register in startup/config detection logic.
3. Pass instance via constructor or dependency injection — no global singletons.
4. Add test with mock/fake provider.

## Related pages

- [architecture/layer-rules.md](../architecture/layer-rules.md)
- [datasets/simulated-bank.md](../datasets/simulated-bank.md)
- [cli/environment-variables.md](../cli/environment-variables.md)

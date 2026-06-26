---
type: Convention
title: Adding a Tool
description: Pure deterministic Python functions in tools/ with mandatory pytest coverage.
resource: tools/
tags: [conventions, tools, testing]
timestamp: 2026-06-26T12:00:00Z
---

# Adding a Tool

## Source of truth

- [tools/](../../tools/) — all deterministic logic
- [tools/__init__.py](../../tools/__init__.py) — public exports
- [CLAUDE.md](../../CLAUDE.md) — "Money math is deterministic"

## What it does

Tools are pure deterministic Python functions. The LLM calls them but never performs their calculations inline. Every new tool ships with a pytest unit test.

## Checklist

1. Create function in appropriate `tools/` module (or new module if logically separate).
2. Add type hints and PEP 257 docstring on every function.
3. Export from `tools/__init__.py` if part of the public budgeting API.
4. Register in [llm/tool_definitions.py](../../llm/tool_definitions.py) if the router should call it.
5. Add `tests/test_<module>.py` with real edge cases — not trivial asserts.

## Rules

- **No LLM imports** inside `tools/`.
- **No DB writes** unless the tool is explicitly a persistence helper (most tools are pure).
- **CHF amounts**: negative = outflow, positive = inflow.
- If computing ratios, splits, or feasibility → it belongs here, not in a skill.

## Example signature

```python
def compute_split(transactions: list[Transaction]) -> SplitResult:
    """Pure math: needs/wants/savings ratios from transactions."""
```

## How to extend

- Mirror existing patterns in [tools/split.py](../../tools/split.py) or [tools/budget.py](../../tools/budget.py).
- Update [wiki/tools/](../tools/) reference page for the new tool.
- Run `pytest -q` before committing.

## Related pages

- [architecture/layer-rules.md](../architecture/layer-rules.md)
- [conventions/testing.md](testing.md)
- [tools/compute-split.md](../tools/compute-split.md)

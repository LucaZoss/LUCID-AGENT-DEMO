# Stage 3 — LLM Layer, Skill Router & TUI REPL

## What this covers

Phase 3 from CLAUDE.md: wiring the LLM into the agent, implementing the two-stage skill loader, building the router loop, and shipping a polished terminal REPL. The deterministic tools from Stage 2 are unchanged; this stage adds everything needed to turn them into a running conversational agent.

---

## Files added / changed

```
LUCID-AGENT-DEMO/
├── llm/
│   ├── __init__.py                     # re-exports LLMProvider, LLMResponse, ToolCall
│   ├── provider.py                     # LLMProvider ABC + ToolCall + LLMResponse
│   ├── config.py                       # provider auto-detection + interactive wizard
│   ├── tool_definitions.py             # JSON-schema tool defs the LLM can call
│   └── adapters/
│       ├── __init__.py
│       └── litellm_adapter.py          # LiteLLM-backed LLMProvider implementation
├── skills/
│   ├── __init__.py
│   ├── skill_loader.py                 # list_skills() + read_skill() — two-stage loading
│   ├── goal_intake/SKILL.md            # stub skill — collect goal + engagement + income
│   ├── recommend_framework/SKILL.md    # stub skill — suggest a plan in plain language
│   ├── build_budget/SKILL.md           # stub skill — derive CHF allocations
│   └── diagnose_overspend/SKILL.md     # stub skill — convert breach → actionable sentence
├── orchestrator/
│   ├── __init__.py
│   ├── context_assembler.py            # FIXED — _recent_transactions now returns Transaction objects
│   ├── router.py                       # route() + handle_message() + tool dispatch
│   └── repl.py                         # polished TUI REPL (rich + pyfiglet)
├── tests/
│   └── test_skill_loader.py            # 16 new tests for the two-stage loader
├── demo_framework_language.py          # two-case demo verifying no methodology names leak
├── requirements.txt                    # pinned runtime deps
└── pyproject.toml                      # CHANGED — added litellm, rich, pyfiglet deps
```

---

## Architecture decisions

### `LLMProvider` interface (`llm/provider.py`)

```python
class LLMProvider(ABC):
    def complete(
        self,
        system: str,
        messages: list[dict],   # OpenAI-style [{role, content}]
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse: ...

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"   # "end_turn" | "tool_use"

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
```

**Key invariant:** vendor SDK imports (`anthropic`, `openai`, …) are permitted **only** inside `llm/adapters/<name>_adapter.py`. Nothing else in the codebase imports a vendor SDK — LiteLLM handles provider routing internally.

### `LiteLLMAdapter` (`llm/adapters/litellm_adapter.py`)

Single implementation of `LLMProvider`. Model string follows LiteLLM conventions:

| String | Provider | Env var needed |
|---|---|---|
| `"claude-sonnet-4-6"` | Anthropic | `ANTHROPIC_API_KEY` |
| `"gpt-4o"` | OpenAI | `OPENAI_API_KEY` |
| `"gemini/gemini-1.5-pro"` | Google | `GOOGLE_API_KEY` |
| `"openai/<model>"` + `api_base=http://localhost:8080/v1` | llama.cpp | — |
| `"openai/<model>"` + `api_base=http://localhost:11434/v1` | Ollama | — |

The adapter silences LiteLLM's verbose success callbacks and translates the OpenAI-style tool-call response into `ToolCall` dataclasses.

### Provider auto-detection (`llm/config.py`)

`build_adapter(model_override=None)` is the single call-site used by the REPL and demo scripts.

Detection order (first match wins):

1. **llama.cpp** — probes `LLAMACPP_URL` (default `:8080/v1`) for `/models`
2. **Anthropic** — `ANTHROPIC_API_KEY` env var
3. **OpenAI** — `OPENAI_API_KEY` env var
4. **Google** — `GOOGLE_API_KEY` env var
5. **Ollama** — probes `OLLAMA_URL` (default `:11434/v1`) for `/models`; picks the first instruction-tuned model
6. **Interactive wizard** — prompts the user to enter a key or local server URL

The interactive wizard uses rich `IntPrompt` / `Prompt.ask`; falls back to plain `input()` when rich is not available.

---

## Two-stage skill loader (`skills/skill_loader.py`)

Mirrors the CLAUDE.md architecture for cheap discovery + on-demand loading:

```python
def list_skills(*, invalidate: bool = False) -> list[dict]:
    """Return [{name, description}, ...] — frontmatter only, module-level cached."""

def read_skill(name: str) -> str:
    """Return the full SKILL.md contents — always reads from disk."""
```

**Stage 1 — manifest scan (cheap, cached):**  
`list_skills()` iterates `skills/*/SKILL.md` and extracts only `name` and `description` from YAML frontmatter. Result is stored in `_MANIFEST_CACHE` for the process lifetime. Calling `list_skills(invalidate=True)` forces a re-scan.

**Stage 2 — full load (on-demand):**  
`read_skill(name)` reads the complete file from disk only after the router has committed to a skill. The body — including tool sequences, example phrasings, and language rules — is never loaded unless the skill is actually needed.

**Frontmatter contract** (standardised across all skills):

```yaml
---
name:           <identifier matching directory name>
description:    <one sentence used by the router for skill matching>
triggers:       <list of example phrases — informational>
tools_required: <list of tool names>
outputs:        <what the skill produces>
---
```

---

## Stub skills (`skills/*/SKILL.md`)

Four skills ship as instructive stubs — the routing and language rules are complete; the full multi-turn flow is deferred.

| Skill | Internal label | Trigger | Key rule |
|---|---|---|---|
| `goal_intake` | — | "save money", "set a goal" | Collects type / engagement / income; never invents a target for open-ended goals |
| `recommend_framework` | `pay_first` / `50_30_20` / `zero_based` | "how should I budget" | See language rules below |
| `build_budget` | — | "build my budget" | Calls `compute_current_split` before any allocation; never does arithmetic itself |
| `diagnose_overspend` | — | "over budget", "overspent" | One sentence + offered action buttons for Telegram |

### Framework language rule (enforced in `recommend_framework/SKILL.md`)

The framework names (`pay_first`, `50_30_20`, `zero_based`) are **internal routing labels only**. The skill SKILL.md contains an explicit banned-terms list and contrasting bad/good phrasing examples baked in:

**Banned in user-facing output:**
`pay-yourself-first`, `50/30/20`, `zero-based`, `allocate`, `discretionary`, `methodology`, `framework`

**Bad (names the method):**
> "I recommend a pay-yourself-first approach. This popular method means you allocate a fixed portion of income before any discretionary spending."

**Good (behaviour-focused, uses their numbers):**
> "Since you'd rather not track every purchase, here's what I'd suggest: the moment your CHF 5,200 salary lands, move CHF 520 straight to savings — that's roughly what you've already been putting aside. Everything left is yours to spend freely, no counting needed."

The routing table (goal type × engagement → internal label) is unchanged internally; only the user-facing explanation is affected.

---

## Router (`orchestrator/router.py`)

### `route(llm, user_message) -> str`

Cheap routing call: the LLM sees only the skill manifest (`{name, description}` pairs) plus the user message. Returns a skill name or `"none"`. No tools, no history.

### `handle_message(llm, conn, user_id, conversation_id, user_message) -> str`

Full turn:

1. **Route** — `route()` returns a skill name (or `"none"`).
2. **Load skill** — `read_skill(name)` fetches the full SKILL.md. Skipped on `"none"`.
3. **Assemble context** — `context_assembler.assemble_context()` rebuilds the system prompt fresh from the DB: goal, split, summary, last-N turns. Skill instructions are prepended to the system prompt.
4. **Tool-calling loop** — up to 10 iterations:
   - Call LLM with `TOOL_DEFINITIONS`.
   - If `stop_reason == "end_turn"`: persist turn, return response.
   - Else: execute each tool in `resp.tool_calls` via `_dispatch_tool`, append results, loop.
5. **Persist** — user + assistant messages written to `messages` table.

### Tool dispatch (`_dispatch_tool`)

| LLM tool name | Python call | Notes |
|---|---|---|
| `compute_current_split` | `tools.compute_split(txns)` | Queries DB for last N days |
| `get_goal_status` | `tools.compute_goal_feasibility(goal, income, savings)` | Constructs `StructuredGoal` from DB row |
| `get_dashboard_summary` | `tools.build_dashboard_payload(period, txns)` | Last 31 days |
| `categorize_merchant` | `tools.categorize_transaction(dummy_txn)` | Dummy outflow txn for lookup |

---

## Context assembler bug fixes (`orchestrator/context_assembler.py`)

Two bugs in the Stage 2 scaffold were fixed during wiring:

1. **`_recent_transactions` returned raw sqlite tuples** — `compute_split` expected `list[Transaction]` objects. Fixed: the query now selects all required fields and constructs `Transaction` dataclasses.

2. **`_live_snapshot` called `compute_goal_feasibility` with wrong arguments** — it passed `goal_row` (a tuple) and `txns` (raw rows) instead of `(StructuredGoal, monthly_income, current_savings)`. Fixed: constructs a `StructuredGoal`, extracts income from the split, and reads savings total from the DB.

Both functions now handle the empty-DB case gracefully (returns `None` for split/feasibility rather than raising).

---

## TUI REPL (`orchestrator/repl.py`)

A styled terminal client backed by `rich` and `pyfiglet`. **All presentation lives here** — the router is client-agnostic.

### Startup

1. `pyfiglet.figlet_format("LUCID AGENT", font="slant")` generates the ASCII art.
2. A cyan → deep-blue vertical gradient (`#67e8f9` → `#1d4ed8`) is applied line-by-line using rich `Text`.
3. Subtitle + two `Rule` separators frame the banner.
4. `build_adapter()` auto-detects the LLM provider; the active model name is shown below the banner.
5. In-memory SQLite seeded with 22 demo transactions (3 months of realistic CHF data).

### Chat loop

| Element | Implementation |
|---|---|
| User prompt | `console.input()` with rich markup: `[bright_blue]›[/bright_blue] [dim]you[/dim]` |
| Thinking indicator | `console.status("thinking…", spinner="dots", spinner_style="#38bdf8")` |
| Agent response | `Panel` with `title="lucid"`, `border_style="#1d4ed8"` |
| Markdown rendering | `Markdown(text)` when response contains ` ``` `, `**`, `##`, etc. |

### Slash commands

| Command | Effect |
|---|---|
| `/help` | Print available commands in a styled panel |
| `/clear` | `console.clear()` + re-render banner; session continues |
| `/quit` / `/exit` | Print "Goodbye." and exit cleanly |

Ctrl-C inside the thinking spinner prints "Cancelled." without a traceback.

### Run

```bash
python -m orchestrator.repl             # auto-detect provider
python -m orchestrator.repl gpt-4o     # force a specific model
```

---

## Tests (`tests/test_skill_loader.py`)

16 new tests, all green. Combined suite: **89 tests, 0 failures**.

```bash
pytest -q
# 89 passed in 0.07s
```

| Class | Tests | What is covered |
|---|---|---|
| `TestParseFrontmatter` | 4 | Name+description extraction; colon in value; no-frontmatter passthrough; unclosed delimiter |
| `TestListSkills` | 5 | Returns list; all entries have name+description; all four stubs present; cache identity; invalidate returns fresh object |
| `TestReadSkill` | 7 | Full content returned; body length check; missing skill raises `FileNotFoundError`; all four stubs readable and start with `---` |

---

## Demo script (`demo_framework_language.py`)

Verifies the framework language rule for two cases without relying on the tool-calling loop (so any local model works):

1. Runs `compute_current_split` locally in Python.
2. Embeds tool output directly in the system prompt alongside the full `recommend_framework` SKILL.md.
3. Calls the LLM for plain text generation (no tool definitions passed).
4. Prints the response in a styled panel.
5. Scans for banned terms and reports pass/fail.

```bash
python demo_framework_language.py
python demo_framework_language.py ollama/mistral:7b-instruct
```

---

## Dependencies added

```
litellm>=1.0    # provider-agnostic LLM calls
rich>=13.0      # terminal styling (REPL panels, spinners, gradient banner)
pyfiglet>=1.0   # ASCII-art banner generation
anthropic>=0.20 # [optional, claude extra] Anthropic SDK loaded by LiteLLM
```

Install:
```bash
pip install -r requirements.txt          # all runtime deps
pip install -e ".[claude]"               # + Anthropic SDK for Claude
```

---

## Architecture rules enforced

- **No vendor SDK imports outside `llm/adapters/`** — `LiteLLMAdapter` is the only file that imports `litellm`.
- **No print statements or terminal code outside `repl.py`** — the router returns plain strings; all styling is the REPL's responsibility.
- **No arithmetic in the LLM** — the four tool definitions expose the deterministic Phase 2 functions; the model calls them, never replicates them.
- **Two-stage skill loading** — the router's first LLM call sees only `{name, description}` manifest entries. Full SKILL.md bodies are loaded only after the routing decision is made.
- **Context assembled fresh every turn** — `assemble_context()` queries the DB on every call; stale remembered figures cannot leak into LLM context.

---

## What is NOT here yet (Phase 4+)

- Full skill implementations (multi-turn `goal_intake` flow, `build_budget` DB persistence)
- `notifier/` — `Notifier` interface, `ConsoleNotifier`, `TelegramNotifier`
- Telegram webhook + inline button routing
- DB persistence of `StructuredGoal` and `Budget` from skill output
- Conversation summary compression (rolling older turns into a summary row)
- SIX open-banking adapter behind the `BankingProvider` interface

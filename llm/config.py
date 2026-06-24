"""
Provider configuration for the LUCID agent.

Detection order:
  1. llama.cpp   — OpenAI-compat server at LLAMACPP_URL (default :8080)
  2. Anthropic   — ANTHROPIC_API_KEY env var
  3. OpenAI      — OPENAI_API_KEY env var
  4. Google      — GOOGLE_API_KEY env var
  5. Ollama      — OpenAI-compat server at OLLAMA_URL (default :11434)
  6. Interactive — ask the user to pick one

detect_all()   — return every detected provider as (label, adapter) pairs.
build_adapter() — the single call-site used by the startup flow and demo scripts.
                  0 detected → interactive setup; 1 → show step + auto-select; >1 → prompt.
"""

from __future__ import annotations

import os
import urllib.request
import urllib.error
import json

from llm.adapters.litellm_adapter import LiteLLMAdapter


# ── .env bootstrap (no external dependency) ────────────────────────────────────

def _load_dotenv(path: str = ".env") -> None:
    """Parse a .env file and inject missing keys into os.environ.

    Only sets keys that are not already in the environment, so shell-exported
    vars always win. Handles quoted values and inline comments.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, raw = line.partition("=")
                key = key.strip()
                # Strip inline comments and optional surrounding quotes
                value = raw.split("#")[0].strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass


_load_dotenv()   # runs once at import time


# ── Probe helpers ──────────────────────────────────────────────────────────────

def _http_get_json(url: str, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _first_model(data: dict) -> str | None:
    """Return the first model ID from an /v1/models response."""
    models = data.get("models") or data.get("data") or []
    if models:
        return models[0].get("id") or models[0].get("name")
    return None


def _probe_openai_compat(base_url: str) -> str | None:
    """Return first available model name if the server is up, else None."""
    data = _http_get_json(f"{base_url}/models")
    if data:
        return _first_model(data)
    return None


# ── Auto-detect (all providers) ───────────────────────────────────────────────

def detect_all() -> list[tuple[str, LiteLLMAdapter]]:
    """Return every available provider as (human-readable label, adapter) pairs.

    All providers are probed; callers decide what to do when 0, 1, or >1 are found.
    """
    results: list[tuple[str, LiteLLMAdapter]] = []

    # 1. llama.cpp
    llamacpp_url = os.getenv("LLAMACPP_URL", "http://localhost:8080/v1")
    mn = _probe_openai_compat(llamacpp_url)
    if mn:
        results.append((
            f"llama.cpp · {mn} ({llamacpp_url})",
            LiteLLMAdapter(model=f"openai/{mn}", api_base=llamacpp_url, api_key="not-needed"),
        ))

    # 2. Anthropic
    if os.getenv("ANTHROPIC_API_KEY"):
        results.append(("Anthropic · claude-sonnet-4-6", LiteLLMAdapter(model="claude-sonnet-4-6")))

    # 3. OpenAI
    if os.getenv("OPENAI_API_KEY"):
        results.append(("OpenAI · gpt-4o", LiteLLMAdapter(model="gpt-4o")))

    # 4. Google
    if os.getenv("GOOGLE_API_KEY"):
        results.append(("Google · gemini-2.5-flash-lite", LiteLLMAdapter(model="gemini/gemini-2.5-flash-lite")))

    # 5. Ollama (OpenAI-compat endpoint) — one entry per installed model
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
    mn = _probe_openai_compat(ollama_url)
    if mn:
        data = _http_get_json(f"{ollama_url}/models") or {}
        models = data.get("models") or data.get("data") or []
        names = [m.get("id") or m.get("name", "") for m in models if m.get("id") or m.get("name")]
        if not names:
            names = [mn]
        for name in names:
            results.append((
                f"Ollama · {name}",
                LiteLLMAdapter(model=f"openai/{name}", api_base=ollama_url, api_key="ollama"),
            ))

    return results


def _cprint(console, msg: str) -> None:
    """Print msg to Rich console if given, else strip markup and print to stdout."""
    if console is not None:
        console.print(msg)
    else:
        import re
        print(re.sub(r"\[/?[^\]]*\]", "", msg))


def _show_provider_step(
    detected: list[tuple[str, LiteLLMAdapter]],
    console=None,
) -> LiteLLMAdapter:
    """Always-visible first step: show available providers and let the user choose.

    * 1 provider  → display it clearly and auto-select (no input required).
    * >1 providers → numbered prompt; user must pick.
    """
    _cprint(console, "\n[bold]── Step 1: Agent provider ──[/bold]\n")
    for i, (label, _) in enumerate(detected, 1):
        _cprint(console, f"  [bold cyan]{i}[/bold cyan]  {label}")
    _cprint(console, "")

    if len(detected) == 1:
        label, adapter = detected[0]
        _cprint(console, f"[dim]Auto-selected (only one provider detected).[/dim]")
        return adapter

    # Multiple providers — require an explicit choice.
    choices = [str(i) for i in range(1, len(detected) + 1)]
    if console is not None:
        try:
            from rich.prompt import IntPrompt
            choice = IntPrompt.ask("Your choice", choices=choices, default=1)
        except (ImportError, EOFError, KeyboardInterrupt):
            choice = 1
    else:
        try:
            choice = int(input(f"Your choice [1-{len(detected)}]: ").strip() or "1")
        except (ValueError, EOFError, KeyboardInterrupt):
            choice = 1

    choice = max(1, min(choice, len(detected)))
    label, adapter = detected[choice - 1]
    _cprint(console, f"[dim]Using: {label}[/dim]")
    return adapter


# ── Interactive selection ──────────────────────────────────────────────────────

def _interactive_setup() -> LiteLLMAdapter:
    """Ask the user to pick a provider; returns a configured adapter."""
    try:
        from rich.console import Console
        from rich.prompt import Prompt, IntPrompt
        console = Console()
    except ImportError:
        console = None  # type: ignore

    def _print(msg: str) -> None:
        if console:
            console.print(msg)
        else:
            print(msg)

    _print("\n[bold]No LLM provider detected.[/bold] Choose one:\n")
    _print("  [bold cyan]1[/bold cyan]  Claude  (Anthropic) — needs ANTHROPIC_API_KEY")
    _print("  [bold cyan]2[/bold cyan]  GPT-4o  (OpenAI)    — needs OPENAI_API_KEY")
    _print("  [bold cyan]3[/bold cyan]  Gemini  (Google)    — needs GOOGLE_API_KEY")
    _print("  [bold cyan]4[/bold cyan]  llama.cpp (local)   — start server, then enter URL")
    _print("  [bold cyan]5[/bold cyan]  Ollama  (local)     — enter model name\n")

    if console:
        choice = IntPrompt.ask("Choice", choices=["1","2","3","4","5"], default=1)
    else:
        choice = int(input("Choice [1-5]: ").strip() or "1")

    def _ask(prompt: str) -> str:
        if console:
            return Prompt.ask(prompt)
        return input(f"{prompt}: ").strip()

    if choice == 1:
        key = _ask("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = key
        return LiteLLMAdapter(model="claude-sonnet-4-6")

    if choice == 2:
        key = _ask("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = key
        return LiteLLMAdapter(model="gpt-4o")

    if choice == 3:
        key = _ask("GOOGLE_API_KEY")
        os.environ["GOOGLE_API_KEY"] = key
        return LiteLLMAdapter(model="gemini/gemini-2.5-flash-lite")

    if choice == 4:
        url = _ask("llama.cpp base URL [http://localhost:8080/v1]") or "http://localhost:8080/v1"
        model = _probe_openai_compat(url)
        if not model:
            _print("[red]Server not reachable.[/red] Is llama.cpp running?")
            raise SystemExit(1)
        return LiteLLMAdapter(model=f"openai/{model}", api_base=url, api_key="not-needed")

    # choice == 5
    url = _ask("Ollama base URL [http://localhost:11434/v1]") or "http://localhost:11434/v1"
    model = _ask("Model name (e.g. mistral:7b-instruct)")
    return LiteLLMAdapter(model=f"openai/{model}", api_base=url, api_key="ollama")


# ── .env persistence helper ───────────────────────────────────────────────────

def _save_to_dotenv(key: str, value: str, dotenv_path: str = ".env") -> None:
    """Upsert KEY=value in a .env file without touching other lines."""
    try:
        try:
            lines = open(dotenv_path).readlines()
        except FileNotFoundError:
            lines = []

        prefix = f"{key}="
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith(prefix):
                new_lines.append(f"{prefix}{value}\n")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"{prefix}{value}\n")

        with open(dotenv_path, "w") as f:
            f.writelines(new_lines)
    except OSError:
        pass   # non-fatal: session env var is already set


# ── Interactive reconfiguration (for /model command) ──────────────────────────

def reconfigure_adapter(console=None) -> LiteLLMAdapter:
    """Let the user pick a new LLM provider interactively.

    Differences from _interactive_setup:
    - Uses getpass so API keys are never echoed to the terminal.
    - Reports the current active provider before showing the menu.
    - Offers to persist the key to a gitignored .env for the next session.
    """
    import getpass as _getpass

    try:
        from rich.prompt import Prompt, IntPrompt
        _c = console
    except ImportError:
        _c = None

    def _print(msg: str) -> None:
        if _c:
            _c.print(msg)
        else:
            print(msg)

    def _ask(prompt: str) -> str:
        if _c:
            return Prompt.ask(prompt)
        return input(f"{prompt}: ").strip()

    def _ask_key(env_var: str) -> str:
        """Read a secret without echo; never log the value."""
        return _getpass.getpass(f"  {env_var}: ")

    def _offer_save(env_var: str, value: str) -> None:
        yn = _ask("  Save to .env for next session? [y/N]").strip().lower()
        if yn == "y":
            _save_to_dotenv(env_var, value)
            _print("[dim]  Saved.[/dim]")

    # ── Show current ──────────────────────────────────────────────────────────
    active: list[str] = []
    if os.getenv("ANTHROPIC_API_KEY"):
        active.append("Claude (Anthropic)")
    if os.getenv("OPENAI_API_KEY"):
        active.append("GPT-4o (OpenAI)")
    if os.getenv("GOOGLE_API_KEY"):
        active.append("Gemini (Google)")
    if active:
        _print(f"\n[dim]Currently configured: {', '.join(active)}[/dim]")

    # ── Provider menu ─────────────────────────────────────────────────────────
    _print("\n[bold]Choose a provider:[/bold]\n")
    _print("  [bold cyan]1[/bold cyan]  Claude   (Anthropic) — frontier")
    _print("  [bold cyan]2[/bold cyan]  GPT-4o   (OpenAI)    — frontier")
    _print("  [bold cyan]3[/bold cyan]  Gemini   (Google)    — frontier")
    _print("  [bold cyan]4[/bold cyan]  llama.cpp (local)    — enter server URL")
    _print("  [bold cyan]5[/bold cyan]  Ollama   (local)     — enter model name\n")

    if _c:
        choice = IntPrompt.ask("Choice", choices=["1","2","3","4","5"], default=1)
    else:
        choice = int(input("Choice [1-5]: ").strip() or "1")

    if choice == 1:
        key = _ask_key("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = key
        _offer_save("ANTHROPIC_API_KEY", key)
        return LiteLLMAdapter(model="claude-sonnet-4-6")

    if choice == 2:
        key = _ask_key("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = key
        _offer_save("OPENAI_API_KEY", key)
        return LiteLLMAdapter(model="gpt-4o")

    if choice == 3:
        key = _ask_key("GOOGLE_API_KEY")
        os.environ["GOOGLE_API_KEY"] = key
        _offer_save("GOOGLE_API_KEY", key)
        return LiteLLMAdapter(model="gemini/gemini-2.5-flash-lite")

    if choice == 4:
        url = _ask("llama.cpp base URL") or "http://localhost:8080/v1"
        model = _probe_openai_compat(url)
        if not model:
            _print("[red]Server not reachable.[/red] Is llama.cpp running?")
            raise SystemExit(1)
        return LiteLLMAdapter(model=f"openai/{model}", api_base=url, api_key="not-needed")

    # choice == 5
    url = _ask("Ollama base URL") or "http://localhost:11434/v1"
    model = _ask("Model name (e.g. mistral:7b-instruct)")
    return LiteLLMAdapter(model=f"openai/{model}", api_base=url, api_key="ollama")


# ── Public API ─────────────────────────────────────────────────────────────────

def build_adapter(
    model_override: str | None = None,
    *,
    console=None,
) -> LiteLLMAdapter:
    """Return a ready-to-use LiteLLMAdapter.

    If *model_override* is given (e.g. from the CLI), use it directly.
    Otherwise: detect_all → 0: interactive setup; ≥1: show provider step (prompt
    when multiple, auto-select when exactly one).
    Pass a Rich Console via *console* for styled output.
    """
    if model_override:
        return LiteLLMAdapter(model=model_override)

    detected = detect_all()

    if not detected:
        return _interactive_setup()

    return _show_provider_step(detected, console)

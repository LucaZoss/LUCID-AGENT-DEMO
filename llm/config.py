"""
Provider configuration for the LUCID agent.

Detection order (first match wins):
  1. llama.cpp   — OpenAI-compat server at LLAMACPP_URL (default :8080)
  2. Anthropic   — ANTHROPIC_API_KEY env var
  3. OpenAI      — OPENAI_API_KEY env var
  4. Google      — GOOGLE_API_KEY env var
  5. Ollama      — OpenAI-compat server at OLLAMA_URL (default :11434)
  6. Interactive — ask the user to pick one

build_adapter() is the single call-site used by repl.py and the demo scripts.
It returns a ready-to-use LiteLLMAdapter.
"""

from __future__ import annotations

import os
import urllib.request
import urllib.error
import json

from llm.adapters.litellm_adapter import LiteLLMAdapter


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


# ── Auto-detect ────────────────────────────────────────────────────────────────

def _detect() -> LiteLLMAdapter | None:
    """Try each provider in order; return an adapter if one is found."""

    # 1. llama.cpp
    llamacpp_url = os.getenv("LLAMACPP_URL", "http://localhost:8080/v1")
    model_name = _probe_openai_compat(llamacpp_url)
    if model_name:
        return LiteLLMAdapter(
            model=f"openai/{model_name}",
            api_base=llamacpp_url,
            api_key="not-needed",
        )

    # 2. Anthropic
    if os.getenv("ANTHROPIC_API_KEY"):
        return LiteLLMAdapter(model="claude-sonnet-4-6")

    # 3. OpenAI
    if os.getenv("OPENAI_API_KEY"):
        return LiteLLMAdapter(model="gpt-4o")

    # 4. Google
    if os.getenv("GOOGLE_API_KEY"):
        return LiteLLMAdapter(model="gemini/gemini-1.5-pro")

    # 5. Ollama (OpenAI-compat endpoint)
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
    model_name = _probe_openai_compat(ollama_url)
    if model_name:
        # Prefer an instruction-tuned model; try to find one
        data = _http_get_json(f"{ollama_url}/models") or {}
        models = data.get("models") or data.get("data") or []
        names = [m.get("id") or m.get("name", "") for m in models]
        preferred = next(
            (n for n in names if any(t in n for t in
             ("instruct", "chat", "qwen", "llama", "phi", "mistral"))),
            model_name,
        )
        return LiteLLMAdapter(
            model=f"openai/{preferred}",
            api_base=ollama_url,
            api_key="ollama",
        )

    return None


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
        return LiteLLMAdapter(model="gemini/gemini-1.5-pro")

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


# ── Public API ─────────────────────────────────────────────────────────────────

def build_adapter(model_override: str | None = None) -> LiteLLMAdapter:
    """Return a ready-to-use LiteLLMAdapter.

    If *model_override* is given (e.g. from the CLI), use it directly.
    Otherwise auto-detect, then fall back to interactive setup.
    """
    if model_override:
        # Honour explicit CLI/env override; for Ollama/llama.cpp the caller
        # should pass the full litellm model string including api_base in kwargs.
        return LiteLLMAdapter(model=model_override)

    adapter = _detect()
    if adapter:
        return adapter

    return _interactive_setup()

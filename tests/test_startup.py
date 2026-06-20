"""Tests for the staged startup state machine (orchestrator/startup.py)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from db.db_schema import init_db
from orchestrator.startup import (
    ACCOUNT_ID,
    CONV_ID,
    USER_ID,
    StartupStage,
    _seed_demo,
    _seed_minimal,
    stage_data_source,
    stage_model,
    stage_persistence,
    stage_summary,
)


class _MockConsole:
    """Minimal Rich console stand-in for testing stage functions."""

    def __init__(self):
        self.printed: list[str] = []

    def print(self, msg="", **kwargs):
        self.printed.append(str(msg))

    def input(self, prompt=""):
        return ""

    def status(self, *args, **kwargs):
        return contextlib.nullcontext()

    def rule(self, *args, **kwargs):
        pass


@pytest.fixture
def mem_db():
    return init_db(":memory:")


# ── stage_model ────────────────────────────────────────────────────────────────

def test_stage_model_single_provider_silent():
    """With exactly one detected provider, adapter is auto-selected without prompting."""
    from llm.adapters.litellm_adapter import LiteLLMAdapter

    fake = LiteLLMAdapter(model="fake-model")
    console = _MockConsole()

    with patch("llm.config.detect_all", return_value=[("Fake · fake-model", fake)]):
        result = stage_model(console)

    assert result is fake
    assert not any("Multiple" in p for p in console.printed)


def test_stage_model_multi_provider_selects_by_index():
    """With multiple detected providers, the user's numbered choice is honoured."""
    from llm.adapters.litellm_adapter import LiteLLMAdapter

    adapter_a = LiteLLMAdapter(model="model-a")
    adapter_b = LiteLLMAdapter(model="model-b")
    console = _MockConsole()

    with patch("llm.config.detect_all", return_value=[
        ("Provider A · model-a", adapter_a),
        ("Provider B · model-b", adapter_b),
    ]):
        with patch("rich.prompt.IntPrompt.ask", return_value=2):
            result = stage_model(console)

    assert result is adapter_b


def test_stage_model_override_bypasses_detection():
    """model_override returns the specified adapter without calling detect_all."""
    console = _MockConsole()
    with patch("llm.config.detect_all") as mock_detect:
        result = stage_model(console, model_override="gpt-4o")

    mock_detect.assert_not_called()
    assert result.model == "gpt-4o"


# ── stage_data_source ─────────────────────────────────────────────────────────

def test_stage_data_source_demo():
    console = _MockConsole()
    with patch("rich.prompt.IntPrompt.ask", return_value=1):
        assert stage_data_source(console) == "demo"


def test_stage_data_source_csv():
    console = _MockConsole()
    with patch("rich.prompt.IntPrompt.ask", return_value=2):
        assert stage_data_source(console) == "csv"


def test_stage_data_source_defaults_demo_on_eoferror():
    """EOFError during prompt defaults to demo mode."""
    console = _MockConsole()
    with patch("rich.prompt.IntPrompt.ask", side_effect=EOFError):
        assert stage_data_source(console) == "demo"


# ── stage_persistence ─────────────────────────────────────────────────────────

def test_stage_persistence_permanent_uses_env_path(tmp_path):
    console = _MockConsole()
    db_path = str(tmp_path / "test.db")
    with patch("rich.prompt.IntPrompt.ask", return_value=1), \
         patch.dict("os.environ", {"LUCID_DB_PATH": db_path}):
        persistence, path = stage_persistence(console)
    assert persistence == "permanent"
    assert path == db_path


def test_stage_persistence_session_returns_memory():
    console = _MockConsole()
    with patch("rich.prompt.IntPrompt.ask", return_value=2):
        persistence, path = stage_persistence(console)
    assert persistence == "session"
    assert path == ":memory:"


def test_stage_persistence_defaults_permanent_on_interrupt():
    console = _MockConsole()
    with patch("rich.prompt.IntPrompt.ask", side_effect=EOFError), \
         patch.dict("os.environ", {}, clear=True):
        persistence, _ = stage_persistence(console)
    assert persistence == "permanent"


# ── stage_summary ─────────────────────────────────────────────────────────────

def test_stage_summary_computes_income_from_real_data(mem_db):
    """Summary output must reflect the actual seeded transactions, not fabricated numbers."""
    _seed_demo(mem_db, USER_ID, ACCOUNT_ID, CONV_ID)
    console = _MockConsole()
    stage_summary(console, mem_db, USER_ID)

    printed = "\n".join(console.printed)
    # Three salary payments of CHF 5200 each = CHF 15,600 income
    assert "15,600.00" in printed or "15600" in printed


def test_stage_summary_empty_ledger_no_crash(mem_db):
    """With no transactions, summary should not raise but print a graceful message."""
    _seed_minimal(mem_db, USER_ID, ACCOUNT_ID, CONV_ID)
    console = _MockConsole()
    stage_summary(console, mem_db, USER_ID)

    printed = "\n".join(console.printed)
    # Total count is 0
    assert "0" in printed


def test_stage_summary_total_count(mem_db):
    """Summary reports the correct total transaction count."""
    _seed_demo(mem_db, USER_ID, ACCOUNT_ID, CONV_ID)
    console = _MockConsole()
    stage_summary(console, mem_db, USER_ID)

    # _seed_demo inserts 22 transactions
    printed = "\n".join(console.printed)
    assert "22" in printed

"""Unit tests for SimulatedBank."""

import pytest
from datetime import datetime, timezone

from contracts import Transaction
from bank.simulated import SimulatedBank


@pytest.fixture
def bank() -> SimulatedBank:
    return SimulatedBank(user_id="test-user", seed=42)


def _manual_txn(bank: SimulatedBank, txn_id: str, amount: float) -> Transaction:
    return Transaction(
        id=txn_id,
        account_id=bank.get_accounts()[0].id,
        amount=amount,
        currency="CHF",
        merchant="Test Merchant",
        category=None,
        ts=datetime.now(timezone.utc),
    )


# ── History generation ───────────────────────────────────────────────────────

def test_generates_at_least_100_transactions(bank):
    txns = bank.get_transactions(bank.get_accounts()[0].id, days=90)
    assert len(txns) >= 100


def test_all_transactions_are_chf(bank):
    txns = bank.get_transactions(bank.get_accounts()[0].id, days=90)
    assert all(t.currency == "CHF" for t in txns)


def test_history_is_chronological(bank):
    txns = bank.get_transactions(bank.get_accounts()[0].id, days=90)
    for a, b in zip(txns, txns[1:]):
        assert a.ts <= b.ts


def test_seeded_output_is_reproducible():
    b1 = SimulatedBank(user_id="u", seed=99)
    b2 = SimulatedBank(user_id="u", seed=99)
    acc_id = b1.get_accounts()[0].id
    t1 = b1.get_transactions(acc_id, 90)
    t2 = b2.get_transactions(acc_id, 90)
    assert len(t1) == len(t2)
    assert [t.amount for t in t1] == [t.amount for t in t2]
    assert [t.merchant for t in t1] == [t.merchant for t in t2]


def test_balance_reflects_history(bank):
    # Balance = BASE + ALL generated history, not the time-filtered get_transactions view.
    expected = round(SimulatedBank._BASE_BALANCE + sum(t.amount for t in bank._history), 2)
    assert bank.get_accounts()[0].balance == pytest.approx(expected, abs=0.01)


# ── Callbacks ────────────────────────────────────────────────────────────────

def test_callback_fires_on_force_transaction(bank):
    received: list[Transaction] = []
    bank.register_callback(received.append)
    bank.force_transaction(_manual_txn(bank, "t-001", -25.00))
    assert len(received) == 1
    assert received[0].amount == pytest.approx(-25.00)


def test_multiple_callbacks_all_fire(bank):
    a: list[Transaction] = []
    b: list[Transaction] = []
    bank.register_callback(a.append)
    bank.register_callback(b.append)
    bank.force_transaction(_manual_txn(bank, "t-002", -10.00))
    assert len(a) == len(b) == 1


def test_replay_history_fires_all_callbacks(bank):
    received: list[Transaction] = []
    bank.register_callback(received.append)
    bank.replay_history()
    # replay_history emits the full internal history, independent of the 90-day window.
    assert len(received) == len(bank._history)


def test_replay_history_is_chronological(bank):
    received: list[Transaction] = []
    bank.register_callback(received.append)
    bank.replay_history()
    for a, b in zip(received, received[1:]):
        assert a.ts <= b.ts


# ── force_transaction side-effects ──────────────────────────────────────────

def test_force_transaction_updates_balance(bank):
    acc = bank.get_accounts()[0]
    before = acc.balance
    bank.force_transaction(_manual_txn(bank, "t-003", -100.00))
    assert bank.get_accounts()[0].balance == pytest.approx(before - 100.00, abs=0.01)


def test_force_transaction_appended_to_history(bank):
    acc_id = bank.get_accounts()[0].id
    before = len(bank.get_transactions(acc_id, days=90))
    bank.force_transaction(_manual_txn(bank, "t-004", -50.00))
    after = len(bank.get_transactions(acc_id, days=90))
    assert after == before + 1


# ── get_accounts ─────────────────────────────────────────────────────────────

def test_returns_one_account(bank):
    assert len(bank.get_accounts()) == 1


def test_account_currency_is_chf(bank):
    assert bank.get_accounts()[0].currency == "CHF"

"""
DBBankingProvider — reads accounts and transactions from the SQLite DB.

Implements BankingProvider against the authoritative in-process DB so the REPL,
slash commands, and agent tools all see the same data. In the demo, the REPL
seeds the DB; in production, SimulatedBank / SixBank would inject rows here.

Satisfies the architecture rule: the REPL only imports this factory, never
the concrete SimulatedBank — swapping to a real bank is still one line.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable

from bank.provider import BankingProvider
from contracts import Account, Transaction


class DBBankingProvider(BankingProvider):
    """Read-only BankingProvider backed by the demo SQLite DB."""

    def __init__(self, conn: sqlite3.Connection, user_id: str) -> None:
        self._conn = conn
        self._user_id = user_id
        self._callbacks: list[Callable[[Transaction], None]] = []

    # ── BankingProvider interface ────────────────────────────────────────────

    def get_accounts(self) -> list[Account]:
        rows = self._conn.execute(
            "SELECT id, user_id, name, balance, currency, account_type, has_income "
            "FROM accounts WHERE user_id=?",
            (self._user_id,),
        ).fetchall()
        return [
            Account(
                id=r[0], user_id=r[1], name=r[2], balance=r[3], currency=r[4],
                account_type=r[5] or "checking", has_income=bool(r[6]),
            )
            for r in rows
        ]

    def get_transactions(self, account_id: str, days: int = 90) -> list[Transaction]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT id, account_id, amount, currency, merchant, category, "
            "line_category, normalized_category, ts, import_batch_id, external_fingerprint "
            "FROM transactions WHERE account_id=? AND ts >= ? ORDER BY ts DESC",
            (account_id, cutoff),
        ).fetchall()
        return [
            Transaction(
                id=r[0], account_id=r[1], amount=r[2], currency=r[3],
                merchant=r[4], category=r[5], line_category=r[6],
                normalized_category=r[7],
                ts=datetime.fromisoformat(r[8]),
                import_batch_id=r[9], external_fingerprint=r[10],
            )
            for r in rows
        ]

    def register_callback(self, cb: Callable[[Transaction], None]) -> None:
        self._callbacks.append(cb)

    def fire_transaction(self, txn: Transaction) -> None:
        """Insert a transaction into the DB and fire all registered callbacks.

        Used by /fire to inject test transactions without touching SimulatedBank.
        Updates the account balance atomically.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO transactions"
            "(id, account_id, amount, currency, merchant, category, line_category, "
            "normalized_category, ts, import_batch_id, external_fingerprint) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                txn.id, txn.account_id, txn.amount, txn.currency,
                txn.merchant, txn.category, txn.line_category,
                txn.normalized_category,
                txn.ts.isoformat(), txn.import_batch_id, txn.external_fingerprint,
            ),
        )
        self._conn.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id=?",
            (txn.amount, txn.account_id),
        )
        self._conn.commit()
        for cb in self._callbacks:
            cb(txn)

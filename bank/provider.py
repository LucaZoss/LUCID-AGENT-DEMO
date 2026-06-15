"""
BankingProvider interface — the ONLY way the rest of the app talks to a bank.

Swapping SimulatedBank for SIX open-banking must be a one-line change at the
wiring layer. Nothing outside bank/ ever imports a concrete implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from contracts import Account, Transaction


class BankingProvider(ABC):

    @abstractmethod
    def get_accounts(self) -> list[Account]:
        """Return all accounts visible to the current user."""

    @abstractmethod
    def get_transactions(self, account_id: str, days: int = 90) -> list[Transaction]:
        """Return transactions for *account_id* going back *days* calendar days."""

    @abstractmethod
    def register_callback(self, cb: Callable[[Transaction], None]) -> None:
        """Register a listener that fires for every incoming transaction.

        Used by the event loop to trigger check_budget without polling.
        Multiple callbacks can be registered; all fire in registration order.
        """

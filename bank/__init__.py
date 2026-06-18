import sqlite3

from bank.provider import BankingProvider
from bank.simulated import SimulatedBank


def make_db_provider(conn: sqlite3.Connection, user_id: str) -> BankingProvider:
    """Wiring-layer factory: return a BankingProvider backed by the demo DB.

    The REPL calls this instead of importing SimulatedBank directly, so
    swapping to a real bank remains a one-line change here.
    """
    from bank.db_provider import DBBankingProvider
    return DBBankingProvider(conn, user_id)


__all__ = ["BankingProvider", "SimulatedBank", "make_db_provider"]

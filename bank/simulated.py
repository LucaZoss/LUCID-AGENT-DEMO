"""
SimulatedBank — a deterministic, seeded stand-in for a real banking backend.

Generates 90 days of realistic CHF transactions for a Zürich-based user.
The seed makes history reproducible across runs, so tests and the demo always
see the same data.

Spending profile target (by % of income):
  Needs   50–60 %   rent + insurance + groceries + transport + utilities
  Wants   25–35 %   dining, bars, coffee, clothing, electronics, entertainment
  Savings 10–20 %   residual after all spending

Public surface beyond BankingProvider:
  force_transaction(txn)  — inject a transaction immediately (fires callbacks)
  replay_history()        — emit all historical transactions through callbacks
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Callable

from bank.provider import BankingProvider
from contracts import Account, Transaction

_GROCERS      = ["Coop", "Migros", "Aldi Suisse", "Lidl Schweiz", "Denner"]
_CAFES        = [
    "Starbucks Zürich HB", "Café Sprüngli", "Coop To Go",
    "Migros Restaurant", "Bächli Café",
]
_RESTAURANTS  = [
    "Tibits Zürich", "Zeughauskeller", "Restaurant Helvetia",
    "Lily's Stomach Supply", "Les Halles Zürich",
    "Mensa ETH Zürich", "SV Group Canteen",
]
_BARS         = [
    "Bar am Wasser", "Bar Rothaus Zürich",
    "Rimini Bar Zürich", "Bar Turbinenplatz",
]
_CLOTHING     = ["Zara Switzerland", "H&M Zürich", "Manor AG", "Globus AG", "Zalando SE"]
_ELECTRONICS  = ["Digitec Galaxus AG", "Interdiscount", "Amazon EU", "Microspot"]
_PHARMA       = ["Apotheke Löwenplatz", "Amavita Apotheke", "Zur Rose AG"]
_ENTERTAINMENT = [
    "Kino Zürich Bellevue", "Halle 622", "Kaufleuten Zürich", "Moods Jazz Club",
]
_INSURERS     = ["CSS Krankenversicherung", "Swica", "Helsana AG"]
_PHONE        = ["Swisscom Mobile", "Sunrise Communications", "Salt Mobile"]


class SimulatedBank(BankingProvider):
    _BASE_BALANCE = 3_000.00  # balance assumed before the simulation window

    def __init__(self, user_id: str, seed: int = 42) -> None:
        self._user_id = user_id
        self._rng = random.Random(seed)
        self._callbacks: list[Callable[[Transaction], None]] = []

        self._accounts: list[Account] = [
            Account(
                id=f"acc-{user_id}-chk",
                user_id=user_id,
                name="Privatkonto",
                balance=self._BASE_BALANCE,
                currency="CHF",
            )
        ]

        self._history: list[Transaction] = self._generate_history(days=90)
        self._accounts[0].balance = round(
            self._BASE_BALANCE + sum(t.amount for t in self._history), 2
        )

    # ── BankingProvider interface ────────────────────────────────────────────

    def get_accounts(self) -> list[Account]:
        return list(self._accounts)

    def get_transactions(self, account_id: str, days: int = 90) -> list[Transaction]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return [
            t for t in self._history
            if t.account_id == account_id and t.ts >= cutoff
        ]

    def register_callback(self, cb: Callable[[Transaction], None]) -> None:
        self._callbacks.append(cb)

    # ── SimulatedBank extras ─────────────────────────────────────────────────

    def force_transaction(self, txn: Transaction) -> None:
        """Inject *txn* immediately: append to history, update balance, fire callbacks."""
        self._history.append(txn)
        for acc in self._accounts:
            if acc.id == txn.account_id:
                acc.balance = round(acc.balance + txn.amount, 2)
                break
        self._emit(txn)

    def replay_history(self) -> None:
        """Emit every historical transaction in chronological order via callbacks."""
        for txn in sorted(self._history, key=lambda t: t.ts):
            self._emit(txn)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _emit(self, txn: Transaction) -> None:
        for cb in self._callbacks:
            cb(txn)

    def _generate_history(self, days: int) -> list[Transaction]:  # noqa: C901
        rng = self._rng
        acc_id = self._accounts[0].id
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        txns: list[Transaction] = []
        counter = 0

        def txn(
            dt: datetime, amount: float, merchant: str, category: str | None
        ) -> Transaction:
            nonlocal counter
            counter += 1
            return Transaction(
                id=f"sim-{counter:05d}",
                account_id=acc_id,
                amount=round(amount, 2),
                currency="CHF",
                merchant=merchant,
                category=category,
                ts=dt,
            )

        def at(dt: datetime, h: int) -> datetime:
            return dt.replace(
                hour=h, minute=rng.randint(0, 59), second=rng.randint(0, 59),
                microsecond=0,
            )

        d = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while d.date() <= now.date():
            dom = d.day
            dow = d.weekday()  # 0=Mon … 6=Sun

            # ── Monthly fixed ────────────────────────────────────────────────
            if dom == 25:   # salary — lower than before to leave realistic surplus
                txns.append(txn(at(d, 8), rng.uniform(6_600, 6_900),
                                "Arbeitgeber AG Zürich", None))

            if dom == 1:    # rent (2 200 reflects Zürich market) + health insurance
                txns.append(txn(at(d, 0), -2_200.00, "Immobilien Zürich AG", "need"))
                txns.append(txn(at(d, 0), -rng.uniform(390, 430),
                                rng.choice(_INSURERS), "need"))

            if dom == 5:    # gym membership
                txns.append(txn(at(d, 7), -89.00, "Fitnesspark AG", "want"))

            if dom == 10:   # home internet
                txns.append(txn(at(d, 9), -69.00, "Quickline AG", "need"))

            if dom == 15:   # SBB Halbtax + mobile phone plan
                txns.append(txn(at(d, 9), -87.00, "SBB Halbtax Abo", "need"))
                txns.append(txn(at(d, 9), -49.00, rng.choice(_PHONE), "need"))

            if dom == 2:    # streaming subscriptions
                txns.append(txn(at(d, 6), -18.90, "Netflix International BV", "want"))
                txns.append(txn(at(d, 6), -11.95, "Spotify AB", "want"))
                txns.append(txn(at(d, 6), -9.90,  "Disney+ Schweiz", "want"))

            if dom == 28:   # electricity / EWZ
                txns.append(txn(at(d, 9), -rng.uniform(72, 88),
                                "EWZ Elektrizitätswerk Zürich", "need"))

            # ── Weekly groceries ─────────────────────────────────────────────
            if dow == 0 and rng.random() < 0.90:            # Monday main shop
                txns.append(txn(at(d, rng.randint(9, 19)),
                                -rng.uniform(100, 185), rng.choice(_GROCERS), "need"))

            if dow == 5 and rng.random() < 0.48:            # Saturday top-up / market
                txns.append(txn(at(d, rng.randint(9, 13)),
                                -rng.uniform(35, 65), rng.choice(_GROCERS), "need"))

            if dow == 3 and rng.random() < 0.55:            # Thursday midweek top-up
                txns.append(txn(at(d, rng.randint(12, 19)),
                                -rng.uniform(28, 70), rng.choice(_GROCERS), "need"))

            # ── Coffee ───────────────────────────────────────────────────────
            if dow < 5 and rng.random() < 0.70:             # weekdays
                txns.append(txn(at(d, rng.randint(7, 9)),
                                -rng.uniform(4.5, 7.5), rng.choice(_CAFES), "want"))
            elif dow >= 5 and rng.random() < 0.35:          # weekends
                txns.append(txn(at(d, rng.randint(9, 11)),
                                -rng.uniform(4.5, 7.5), rng.choice(_CAFES), "want"))

            # ── Dining out ───────────────────────────────────────────────────
            if dow >= 4 and rng.random() < 0.73:            # Fri–Sun primary sit-down
                txns.append(txn(at(d, rng.randint(12, 21)),
                                -rng.uniform(48, 120), rng.choice(_RESTAURANTS), "want"))
            if dow == 5 and rng.random() < 0.22:            # extra Saturday visit
                txns.append(txn(at(d, rng.randint(19, 22)),
                                -rng.uniform(50, 110), rng.choice(_RESTAURANTS), "want"))
            if dow < 4 and rng.random() < 0.42:             # weekday lunches
                txns.append(txn(at(d, rng.randint(12, 14)),
                                -rng.uniform(15, 32), rng.choice(_RESTAURANTS), "want"))

            # ── Bars / nightlife (Friday + Saturday evenings) ─────────────────
            if (dow == 4 or dow == 5) and rng.random() < 0.27:
                txns.append(txn(at(d, rng.randint(20, 23)),
                                -rng.uniform(38, 88), rng.choice(_BARS), "want"))

            # ── Public transport (occasional extra ticket) ────────────────────
            if dow < 5 and rng.random() < 0.15:
                txns.append(txn(at(d, rng.randint(7, 18)),
                                -rng.uniform(12, 54), "SBB CFF FFS", "need"))

            # ── Clothing / fashion ────────────────────────────────────────────
            if rng.random() < 0.06:
                txns.append(txn(at(d, rng.randint(10, 19)),
                                -rng.uniform(60, 220), rng.choice(_CLOTHING), "want"))

            # ── Pharmacy / Drogerie ───────────────────────────────────────────
            if rng.random() < 0.07:
                txns.append(txn(at(d, rng.randint(9, 18)),
                                -rng.uniform(12, 55), rng.choice(_PHARMA), "need"))

            # ── Electronics / online shopping ─────────────────────────────────
            if rng.random() < 0.035:
                txns.append(txn(at(d, rng.randint(0, 23)),
                                -rng.uniform(45, 350), rng.choice(_ELECTRONICS), "want"))

            # ── Entertainment (evenings, weekends) ────────────────────────────
            if dow >= 4 and rng.random() < 0.22:
                txns.append(txn(at(d, rng.randint(17, 22)),
                                -rng.uniform(22, 95), rng.choice(_ENTERTAINMENT), "want"))

            d += timedelta(days=1)

        return sorted(txns, key=lambda t: t.ts)

#!/usr/bin/env python3
"""
Phase 1 demo: replay 90 days of CHF transactions, then fire one manually.

Run:
    python demo_bank.py
    python demo_bank.py --force-merchant "Migros" --force-amount -88.50
"""

import argparse
from datetime import datetime, timezone

from bank.simulated import SimulatedBank
from contracts import Transaction


def _fmt(txn: Transaction) -> str:
    sign = "+" if txn.amount >= 0 else ""
    cat = f"  [{txn.category}]" if txn.category else ""
    return (
        f"  {txn.ts.strftime('%Y-%m-%d %H:%M')}  "
        f"{sign}{txn.amount:>10.2f} CHF  "
        f"{txn.merchant:<35}{cat}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="SimulatedBank demo")
    parser.add_argument("--force-merchant", default="Starbucks Zürich HB")
    parser.add_argument("--force-amount", type=float, default=-6.50)
    args = parser.parse_args()

    bank = SimulatedBank(user_id="demo-user", seed=42)
    received: list[Transaction] = []

    def on_txn(txn: Transaction) -> None:
        received.append(txn)
        print(_fmt(txn))

    bank.register_callback(on_txn)

    print("=" * 70)
    print("  90-day CHF transaction history (SimulatedBank, seed=42)")
    print("=" * 70)
    bank.replay_history()

    income = sum(t.amount for t in received if t.amount > 0)
    outflow = sum(t.amount for t in received if t.amount < 0)
    acc = bank.get_accounts()[0]

    print()
    print(f"  {len(received)} transactions  |  "
          f"Income: +{income:,.2f} CHF  |  "
          f"Outflow: {outflow:,.2f} CHF")
    print(f"  Current balance: {acc.balance:,.2f} CHF")

    print()
    print("=" * 70)
    print("  Firing a manual transaction via force_transaction()")
    print("=" * 70)

    manual = Transaction(
        id="manual-001",
        account_id=acc.id,
        amount=args.force_amount,
        currency="CHF",
        merchant=args.force_merchant,
        category=None,
        ts=datetime.now(timezone.utc),
    )
    bank.force_transaction(manual)
    print(f"\n  New balance: {bank.get_accounts()[0].balance:,.2f} CHF")
    print("Done.")


if __name__ == "__main__":
    main()

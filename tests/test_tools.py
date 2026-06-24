"""Unit tests for the Phase 2 deterministic tools."""

from __future__ import annotations

import pytest
from datetime import date, datetime, timezone

from contracts import Budget, StructuredGoal, Transaction
from tools.categorize import categorize_transaction
from tools.split import SplitResult, compute_split
from tools.feasibility import compute_goal_feasibility
from tools.budget import BudgetBreach, check_budget
from tools.dashboard import build_dashboard_payload


# ── Helpers ──────────────────────────────────────────────────────────────────

def _txn(
    merchant: str,
    amount: float,
    category: str | None = None,
    txn_id: str = "t-000",
    normalized_category: str | None = None,
) -> Transaction:
    return Transaction(
        id=txn_id,
        account_id="acc-1",
        amount=amount,
        currency="CHF",
        merchant=merchant,
        category=category,
        normalized_category=normalized_category,
        ts=datetime.now(timezone.utc),
    )


def _salary(amount: float = 7_200.0) -> Transaction:
    return _txn("Arbeitgeber AG", amount, txn_id="salary-1")


def _demo_budget(period: str = "2026-06") -> Budget:
    return Budget(
        id="b-1",
        user_id="u-1",
        allocations={"need": 3_500.0, "want": 2_000.0, "savings": 1_500.0},
        target_ratios={"needs": 0.49, "wants": 0.28, "savings": 0.21},
        period=period,
    )


def _demo_goal(
    goal_type: str = "target",
    amount: float = 10_000.0,
    target_date: date = date(2027, 6, 1),
) -> StructuredGoal:
    return StructuredGoal(
        id="g-1",
        user_id="u-1",
        goal_type=goal_type,
        engagement="high",
        amount=amount if goal_type == "target" else None,
        target_date=target_date if goal_type == "target" else None,
        framework="zero_based",
    )


# ══════════════════════════════════════════════════════════════════════════════
# categorize_transaction
# ══════════════════════════════════════════════════════════════════════════════

class TestCategorizeTransaction:

    def test_grocery_stores_are_needs(self):
        for merchant in ["Coop", "Migros", "Aldi Suisse", "Denner", "Volg", "Lidl Schweiz"]:
            assert categorize_transaction(_txn(merchant, -50.0)) == "need", merchant

    def test_health_insurance_is_need(self):
        for merchant in ["CSS Krankenversicherung", "Helsana AG", "Swica"]:
            assert categorize_transaction(_txn(merchant, -420.0)) == "need", merchant

    def test_rent_and_housing_are_needs(self):
        assert categorize_transaction(_txn("Immobilien Zürich AG", -1800.0)) == "need"

    def test_transport_is_need(self):
        for merchant in ["SBB CFF FFS", "SBB Halbtax Abo", "ZVV"]:
            assert categorize_transaction(_txn(merchant, -87.0)) == "need", merchant

    def test_telecom_is_need(self):
        for merchant in ["Swisscom Mobile", "Sunrise Communications", "Salt Mobile"]:
            assert categorize_transaction(_txn(merchant, -49.0)) == "need", merchant

    def test_pharmacy_is_need(self):
        for merchant in ["Apotheke Löwenplatz", "Amavita Apotheke", "Zur Rose AG"]:
            assert categorize_transaction(_txn(merchant, -30.0)) == "need", merchant

    def test_cafes_and_dining_are_wants(self):
        for merchant in [
            "Starbucks Zürich HB", "Café Sprüngli", "Tibits Zürich",
            "Zeughauskeller", "Lily's Stomach Supply",
        ]:
            assert categorize_transaction(_txn(merchant, -15.0)) == "want", merchant

    def test_migros_restaurant_is_want_not_need(self):
        # "restaurant" pattern must fire before "migros"
        assert categorize_transaction(_txn("Migros Restaurant", -14.0)) == "want"

    def test_coop_to_go_is_want_not_need(self):
        # "to go" pattern must fire before "coop"
        assert categorize_transaction(_txn("Coop To Go", -6.0)) == "want"

    def test_entertainment_is_want(self):
        for merchant in ["Netflix International BV", "Spotify AB", "Halle 622", "Moods Jazz Club"]:
            assert categorize_transaction(_txn(merchant, -15.0)) == "want", merchant

    def test_clothing_is_want(self):
        for merchant in ["Zara Switzerland", "H&M Zürich", "Zalando SE", "Globus AG"]:
            assert categorize_transaction(_txn(merchant, -80.0)) == "want", merchant

    def test_electronics_is_want(self):
        for merchant in ["Digitec Galaxus AG", "Interdiscount", "Amazon EU"]:
            assert categorize_transaction(_txn(merchant, -150.0)) == "want", merchant

    def test_gym_is_want(self):
        assert categorize_transaction(_txn("Fitnesspark AG", -89.0)) == "want"

    def test_savings_vehicles(self):
        for merchant in ["VIAC AG", "Frankly AG", "Swissquote Bank"]:
            assert categorize_transaction(_txn(merchant, -500.0)) == "savings", merchant

    def test_unknown_merchant_defaults_to_want(self):
        assert categorize_transaction(_txn("Unbekannter Laden XYZ", -25.0)) == "want"

    def test_raises_on_positive_amount(self):
        with pytest.raises(ValueError, match="outflow"):
            categorize_transaction(_txn("Arbeitgeber AG", +7_200.0))

    def test_raises_on_zero_amount(self):
        with pytest.raises(ValueError):
            categorize_transaction(_txn("Coop", 0.0))

    def test_pre_set_category_ignored_by_function(self):
        # categorize_transaction always looks at merchant, never txn.category
        txn = _txn("Coop", -50.0, category="want")   # wrong pre-set
        assert categorize_transaction(txn) == "need"  # merchant wins


# ══════════════════════════════════════════════════════════════════════════════
# compute_split
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeSplit:

    def _simple_txns(self) -> list[Transaction]:
        return [
            _salary(6_000.0),
            _txn("Immobilien Zürich AG", -1_800.0, "need", "t-1"),
            _txn("Migros",               -  400.0, "need", "t-2"),
            _txn("Tibits Zürich",        -  200.0, "want", "t-3"),
            _txn("Starbucks",            -   50.0, "want", "t-4"),
        ]

    def test_income_is_correctly_summed(self):
        r = compute_split(self._simple_txns())
        assert r.income_chf == pytest.approx(6_000.0)

    def test_needs_chf_correct(self):
        r = compute_split(self._simple_txns())
        assert r.needs_chf == pytest.approx(2_200.0)

    def test_wants_chf_correct(self):
        r = compute_split(self._simple_txns())
        assert r.wants_chf == pytest.approx(250.0)

    def test_residual_savings_correct(self):
        r = compute_split(self._simple_txns())
        assert r.residual_savings_chf == pytest.approx(6_000.0 - 2_200.0 - 250.0)

    def test_pcts_sum_to_100(self):
        r = compute_split(self._simple_txns())
        total = r.needs_pct + r.wants_pct + r.savings_pct
        assert total == pytest.approx(100.0, abs=0.5)  # rounding tolerance

    def test_uses_preset_category_when_set(self):
        # category="need" on the transaction should be respected
        txns = [_salary(1_000.0), _txn("UnknownMerchant", -200.0, category="need", txn_id="t-x")]
        r = compute_split(txns)
        assert r.needs_chf == pytest.approx(200.0)
        assert r.wants_chf == pytest.approx(0.0)

    def test_falls_back_to_categorizer_when_category_none(self):
        txns = [_salary(1_000.0), _txn("Coop", -100.0, category=None, txn_id="t-x")]
        r = compute_split(txns)
        assert r.needs_chf == pytest.approx(100.0)

    def test_explicit_savings_tracked_separately(self):
        txns = [
            _salary(5_000.0),
            _txn("VIAC AG", -500.0, category="savings", txn_id="t-s"),
            _txn("Coop",    -300.0, category="need",    txn_id="t-n"),
        ]
        r = compute_split(txns)
        assert r.explicit_savings_chf == pytest.approx(500.0)
        assert r.needs_chf == pytest.approx(300.0)

    def test_spend_composition_mode_without_income(self):
        # No income → spend_composition mode; percentages are share of total spend
        txns = [_txn("Coop", -100.0, "need")]
        r = compute_split(txns)
        assert r.mode == "spend_composition"
        assert r.needs_pct == pytest.approx(100.0)
        assert r.wants_pct == pytest.approx(0.0)

    def test_needs_pct_formula(self):
        r = compute_split(self._simple_txns())
        assert r.needs_pct == pytest.approx(2_200.0 / 6_000.0 * 100, abs=0.2)

    def test_wants_pct_pinned(self):
        r = compute_split(self._simple_txns())
        # hand-verified: wants=250, income=6000 → 250/6000*100 = 4.2 %
        assert r.wants_pct == pytest.approx(4.2, abs=0.1)

    def test_savings_pct_pinned(self):
        r = compute_split(self._simple_txns())
        # hand-verified: residual=6000-2200-250=3550 → 3550/6000*100 = 59.2 %
        assert r.savings_pct == pytest.approx(59.2, abs=0.1)

    def test_normalized_category_takes_priority_over_raw_category(self):
        # raw category says "want" but normalized_category says "rent" (Needs → need)
        txns = [
            _salary(1_000.0),
            _txn("SomeShop", -200.0, category="want",
                 normalized_category="rent", txn_id="t-n"),
        ]
        r = compute_split(txns)
        assert r.needs_chf == pytest.approx(200.0)
        assert r.wants_chf == pytest.approx(0.0)

    def test_income_normalized_category_excluded_from_nws(self):
        # twint_credit (Extras) → derive_legacy_bucket returns None → skipped
        txns = [
            _salary(1_000.0),
            _txn("Twint", -50.0, category="want",
                 normalized_category="twint_debit", txn_id="t-twint"),
        ]
        r = compute_split(txns)
        # twint_debit has no NWS bucket → excluded; only income present
        assert r.needs_chf == pytest.approx(0.0)
        assert r.wants_chf == pytest.approx(0.0)

    def test_overspending_negative_residual(self):
        # outflow (800+400=1200) > income (1000) → residual is -200
        txns = [
            _salary(1_000.0),
            _txn("Migros",        - 800.0, "need", "t-a"),
            _txn("Tibits Zürich", - 400.0, "want", "t-b"),
        ]
        r = compute_split(txns)
        # residual stored as negative; savings_chf clamped to 0
        assert r.residual_savings_chf == pytest.approx(-200.0)
        assert r.savings_chf          == pytest.approx(0.0)
        assert r.savings_pct          == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════════════
# compute_goal_feasibility
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeGoalFeasibility:

    def test_target_goal_required_monthly(self):
        goal = _demo_goal(amount=12_000.0, target_date=date(2027, 6, 1))
        r = compute_goal_feasibility(goal, monthly_income=7_200.0,
                                     current_savings=0.0,
                                     reference_date=date(2026, 6, 1))
        # 12 months remaining → 12 000 / 12 = 1 000 CHF/month
        assert r.required_monthly_chf == pytest.approx(1_000.0, abs=5.0)

    def test_target_goal_on_track_when_affordable(self):
        goal = _demo_goal(amount=5_000.0, target_date=date(2027, 6, 1))
        r = compute_goal_feasibility(goal, monthly_income=7_200.0,
                                     current_savings=0.0,
                                     reference_date=date(2026, 6, 1))
        assert r.on_track is True

    def test_target_goal_off_track_when_impossible(self):
        # 100 000 CHF in 1 month on 7 200 income → impossible
        goal = _demo_goal(amount=100_000.0, target_date=date(2026, 7, 1))
        r = compute_goal_feasibility(goal, monthly_income=7_200.0,
                                     current_savings=0.0,
                                     reference_date=date(2026, 6, 1))
        assert r.on_track is False

    def test_partial_savings_reduce_required(self):
        goal = _demo_goal(amount=10_000.0, target_date=date(2027, 6, 1))
        r_zero = compute_goal_feasibility(goal, monthly_income=7_200.0,
                                          current_savings=0.0,
                                          reference_date=date(2026, 6, 1))
        r_half = compute_goal_feasibility(goal, monthly_income=7_200.0,
                                          current_savings=5_000.0,
                                          reference_date=date(2026, 6, 1))
        assert r_half.required_monthly_chf < r_zero.required_monthly_chf
        # hand-verified: still_needed=5000, months≈12 → required≈416.95
        assert r_half.still_needed_chf == pytest.approx(5_000.0)
        assert r_half.required_monthly_chf == pytest.approx(417.0, abs=10.0)

    def test_deadline_passed_returns_inf(self):
        # target date in the past → impossible, must signal infinite required rate
        goal = _demo_goal(amount=5_000.0, target_date=date(2025, 1, 1))
        r = compute_goal_feasibility(goal, monthly_income=7_200.0,
                                     current_savings=3_000.0,
                                     reference_date=date(2026, 6, 1))
        import math
        assert math.isinf(r.required_monthly_chf)
        assert r.on_track is False
        assert r.months_remaining == 0.0

    def test_open_goal_is_always_on_track(self):
        goal = _demo_goal(goal_type="open")
        r = compute_goal_feasibility(goal, monthly_income=7_200.0, current_savings=0.0)
        assert r.on_track is True

    def test_open_goal_suggests_10_pct(self):
        goal = _demo_goal(goal_type="open")
        r = compute_goal_feasibility(goal, monthly_income=7_200.0, current_savings=0.0)
        assert r.required_monthly_chf == pytest.approx(720.0)

    def test_months_remaining_correct(self):
        goal = _demo_goal(amount=6_000.0, target_date=date(2027, 6, 1))
        r = compute_goal_feasibility(goal, monthly_income=7_200.0,
                                     current_savings=0.0,
                                     reference_date=date(2026, 6, 1))
        assert r.months_remaining == pytest.approx(12.0, abs=0.5)

    def test_raises_on_zero_income(self):
        with pytest.raises(ValueError):
            compute_goal_feasibility(_demo_goal(), monthly_income=0.0, current_savings=0.0)


# ══════════════════════════════════════════════════════════════════════════════
# check_budget
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckBudget:

    def _txns_under_limit(self) -> list[Transaction]:
        return [
            _txn("Migros", -500.0, category="need", txn_id="t-1"),
            _txn("Coop",   -400.0, category="need", txn_id="t-2"),
        ]  # 900 of 3500 limit used

    def test_no_breach_when_under_limit(self):
        budget = _demo_budget()
        new_txn = _txn("Denner", -200.0, category="need", txn_id="t-new")
        result = check_budget(new_txn, budget, self._txns_under_limit())
        assert result is None

    def test_breach_returned_when_over_limit(self):
        budget = _demo_budget()
        # 3500 limit; already 900 spent; push 2700 more = 3600 total → breach
        new_txn = _txn("Aldi Suisse", -2_700.0, category="need", txn_id="t-new")
        result = check_budget(new_txn, budget, self._txns_under_limit())
        assert isinstance(result, BudgetBreach)

    def test_breach_has_correct_overage(self):
        budget = _demo_budget()
        new_txn = _txn("Aldi Suisse", -2_700.0, category="need", txn_id="t-new")
        result = check_budget(new_txn, budget, self._txns_under_limit())
        assert result is not None
        # 900 + 2700 = 3600; 3600 − 3500 = 100 overage
        assert result.overage_chf == pytest.approx(100.0)

    def test_breach_overage_pct(self):
        budget = _demo_budget()
        new_txn = _txn("Aldi Suisse", -2_700.0, category="need", txn_id="t-new")
        result = check_budget(new_txn, budget, self._txns_under_limit())
        assert result is not None
        # 100 / 3500 * 100 = 2.9 %
        assert result.overage_pct == pytest.approx(100.0 / 3_500.0 * 100, abs=0.2)

    def test_income_transactions_ignored(self):
        budget = _demo_budget()
        income_txn = _txn("Arbeitgeber AG", +7_200.0, txn_id="salary")
        assert check_budget(income_txn, budget, []) is None

    def test_no_breach_when_category_not_in_budget(self):
        budget = Budget(
            id="b-2", user_id="u-1",
            allocations={"want": 2_000.0},  # no "need" key
            target_ratios={},
            period="2026-06",
        )
        new_txn = _txn("Migros", -9_999.0, category="need", txn_id="t-x")
        assert check_budget(new_txn, budget, []) is None

    def test_uses_categorizer_when_category_none(self):
        budget = _demo_budget()
        # Coop → "need"; category not pre-set
        new_txn = _txn("Coop", -3_600.0, category=None, txn_id="t-x")
        result = check_budget(new_txn, budget, [])
        assert isinstance(result, BudgetBreach)
        assert result.category == "need"

    def test_period_transactions_counted(self):
        budget = _demo_budget()
        period = [
            _txn("Coop",   -1_700.0, "need", "old-1"),
            _txn("Migros", -1_700.0, "need", "old-2"),
        ]  # 3400 of 3500 used
        # Next grocery just barely stays under
        ok_txn = _txn("Denner", -99.0, "need", "new-1")
        assert check_budget(ok_txn, budget, period) is None
        # But this one pushes it over
        over_txn = _txn("Denner", -101.0, "need", "new-2")
        assert check_budget(over_txn, budget, period) is not None

    def test_no_breach_exactly_at_limit(self):
        # 3400 already spent; +100 = 3500 = limit exactly → NOT a breach
        budget = _demo_budget()
        period = [
            _txn("Coop",   -1_700.0, "need", "old-1"),
            _txn("Migros", -1_700.0, "need", "old-2"),
        ]
        at_limit_txn = _txn("Denner", -100.0, "need", "t-exact")
        assert check_budget(at_limit_txn, budget, period) is None


# ══════════════════════════════════════════════════════════════════════════════
# build_dashboard_payload
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildDashboardPayload:

    def _base_txns(self) -> list[Transaction]:
        return [
            _salary(7_200.0),
            _txn("Immobilien Zürich AG", -1_800.0, "need",  "t-1"),
            _txn("Migros",               -  500.0, "need",  "t-2"),
            _txn("Coop",                 -  300.0, "need",  "t-3"),
            _txn("Tibits Zürich",        -  150.0, "want",  "t-4"),
            _txn("Starbucks Zürich HB",  -   60.0, "want",  "t-5"),
            _txn("Netflix",              -   19.0, "want",  "t-6"),
        ]

    def test_returns_dashboard_payload(self):
        from tools.dashboard import DashboardPayload
        result = build_dashboard_payload("2026-06", self._base_txns())
        assert isinstance(result, DashboardPayload)
        # hand-verified: needs=1800+500+300=2600, wants=150+60+19=229
        assert result.split.needs_chf == pytest.approx(2_600.0)
        assert result.split.wants_chf == pytest.approx(229.0)

    def test_income_correct(self):
        result = build_dashboard_payload("2026-06", self._base_txns())
        assert result.income_chf == pytest.approx(7_200.0)

    def test_net_is_income_minus_outflow(self):
        result = build_dashboard_payload("2026-06", self._base_txns())
        # hand-verified: income=7200, outflow=1800+500+300+150+60+19=2829, net=4371
        assert result.net_chf == pytest.approx(4_371.0, abs=0.01)

    def test_top_merchants_sorted_by_spend(self):
        result = build_dashboard_payload("2026-06", self._base_txns())
        totals = [m.total_chf for m in result.top_merchants]
        assert totals == sorted(totals, reverse=True)

    def test_top_merchants_max_10(self):
        txns = [_salary()] + [
            _txn(f"Shop {i}", -float(i * 10), "want", f"t-{i}")
            for i in range(1, 20)
        ]
        result = build_dashboard_payload("2026-06", txns)
        assert len(result.top_merchants) <= 10

    def test_category_breakdown_has_three_rows(self):
        result = build_dashboard_payload("2026-06", self._base_txns())
        cats = {c.category for c in result.category_breakdown}
        assert cats == {"need", "want", "savings"}

    def test_budget_vs_actual_populated_when_budget_given(self):
        result = build_dashboard_payload("2026-06", self._base_txns(), budget=_demo_budget())
        assert result.budget_vs_actual is not None
        assert len(result.budget_vs_actual) == 3

    def test_budget_vs_actual_is_none_without_budget(self):
        result = build_dashboard_payload("2026-06", self._base_txns())
        assert result.budget_vs_actual is None

    def test_goal_progress_populated_when_goal_given(self):
        result = build_dashboard_payload(
            "2026-06", self._base_txns(),
            goal=_demo_goal(), current_savings=2_000.0, monthly_income=7_200.0,
        )
        assert result.goal_progress is not None
        assert result.goal_progress["saved_chf"] == pytest.approx(2_000.0)

    def test_goal_progress_is_none_without_goal(self):
        result = build_dashboard_payload("2026-06", self._base_txns())
        assert result.goal_progress is None

    def test_period_stored_correctly(self):
        result = build_dashboard_payload("2026-05", self._base_txns())
        assert result.period == "2026-05"

    def test_normalized_breakdown_populated_when_normalized_category_set(self):
        txns = [
            _salary(7_200.0),
            _txn("Migros", -500.0, "need", "t-g", normalized_category="groceries_food"),
            _txn("Tibits",  -150.0, "want", "t-r", normalized_category="restaurants"),
            _txn("Netflix",  -19.0, "want", "t-d", normalized_category="digital_goods"),
        ]
        result = build_dashboard_payload("2026-06", txns)
        assert result.normalized_breakdown is not None
        assert result.normalized_breakdown["groceries_food"] == pytest.approx(500.0)
        assert result.normalized_breakdown["restaurants"] == pytest.approx(150.0)
        assert result.normalized_breakdown["digital_goods"] == pytest.approx(19.0)

    def test_normalized_breakdown_is_none_without_normalized_category(self):
        txns = [
            _salary(7_200.0),
            _txn("Migros", -500.0, "need", "t-g"),  # no normalized_category
        ]
        result = build_dashboard_payload("2026-06", txns)
        assert result.normalized_breakdown is None

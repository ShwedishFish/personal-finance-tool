from datetime import date

import pytest

from app.finance.debt import Debt, payoff_plan
from app.finance.networth import Snapshot, allocation, net_worth_history


def test_simple_payoff_without_interest():
    result = payoff_plan([Debt("Loan", 1_000, 0.0, 100)])
    assert result["paid_off"] and result["months"] == 10
    assert result["total_interest"] == 0


def test_avalanche_saves_interest_and_extra_payment_helps():
    debts = [Debt("Card", 5_000, 0.24, 150), Debt("Car", 3_000, 0.05, 150)]
    avalanche = payoff_plan(debts, extra_monthly=200, strategy="avalanche")
    snowball = payoff_plan(debts, extra_monthly=200, strategy="snowball")
    minimum = payoff_plan(debts, strategy="avalanche")
    assert avalanche["total_interest"] < snowball["total_interest"]
    assert avalanche["months"] < minimum["months"]


def test_payment_below_interest_never_pays_off():
    result = payoff_plan([Debt("Card", 10_000, 0.30, 100)])
    assert not result["paid_off"] and result["months"] is None


def test_net_worth_history_carries_balances_forward():
    snaps = [
        Snapshot(1, date(2026, 1, 1), 1_000, False),
        Snapshot(2, date(2026, 1, 1), 300, True),
        Snapshot(1, date(2026, 2, 1), 1_500, False),
    ]
    history = net_worth_history(snaps)
    assert [h["net_worth"] for h in history] == [700, 1_200]
    assert history[1]["liabilities"] == 300


def test_allocation_shares():
    result = allocation([("stocks", 75), ("bonds", 25), ("stocks", 0)])
    assert result[0] == {"asset_class": "stocks", "value": 75, "share": pytest.approx(0.75)}

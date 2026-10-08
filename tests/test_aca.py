from dataclasses import replace

import pytest

from app.finance.aca import applicable_percentage, poverty_line, premium_tax_credit
from app.finance.projection import FlowInput, ProjectionInput, simulate


def test_applicable_percentage_bands_and_cliff():
    assert applicable_percentage(0.8) == pytest.approx(0.021)
    assert applicable_percentage(1.40) == pytest.approx(0.0314 + 0.0105 * 0.07 / 0.17)
    assert applicable_percentage(2.0) == pytest.approx(0.066)
    assert applicable_percentage(3.5) == pytest.approx(0.0996)
    assert applicable_percentage(4.0) == pytest.approx(0.0996)
    assert applicable_percentage(4.01) is None


def test_premium_tax_credit():
    assert poverty_line(2) == 21_150
    magi = 60_000
    pct = 0.0844 + 0.0152 * (magi / 21_150 - 2.5) / 0.5
    assert premium_tax_credit(magi, 2, 20_000) == pytest.approx(20_000 - pct * magi)
    assert premium_tax_credit(4.01 * 21_150, 2, 20_000) == 0.0  # the 400% cliff
    assert premium_tax_credit(200_000, 2, 20_000) == 0.0
    assert premium_tax_credit(30_000, 1, 1_000) == 0.0  # expected contribution exceeds the benchmark
    # The poverty line scales with inflation, so the same real income gets the same real credit.
    assert premium_tax_credit(2 * magi, 2, 40_000, scale=2.0) == pytest.approx(2 * premium_tax_credit(magi, 2, 20_000))


def early_retiree(**overrides) -> ProjectionInput:
    base = dict(
        current_age=60, retirement_age=60, life_expectancy=70, start_year=2026, inflation=0.0,
        taxable=1_000_000, taxable_basis=1_000_000,
        flows=[
            FlowInput("Living", "expense", 30_000, 60, 70),
            FlowInput("Health insurance before Medicare", "expense", 12_000, 60, 64, category="healthcare"),
        ],
        aca_benchmarks=[FlowInput("ACA benchmark premium", "expense", 10_000, 60, 64, category="healthcare")],
    )
    base.update(overrides)
    return ProjectionInput(**base)


def test_low_income_early_retiree_gets_credit_until_medicare():
    inp = early_retiree()
    rows = simulate(inp)
    before, after = rows[:5], rows[5:]
    assert all(r.aca_credit > 5_000 for r in before)  # withdrawals of basis are not income
    assert all(r.aca_credit == 0 for r in after)
    no_aca = simulate(replace(inp, aca_benchmarks=[]))
    assert rows[0].expenses == pytest.approx(no_aca[0].expenses - rows[0].aca_credit)
    assert rows[-1].investable > no_aca[-1].investable


def test_high_income_gets_no_credit():
    rows = simulate(early_retiree(flows=early_retiree().flows + [FlowInput("Pension", "income", 90_000, 60, 70,
                                                                             tax_type="ordinary")]))
    assert all(r.aca_credit == 0 for r in rows)

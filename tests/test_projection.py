import pytest

from app.finance.projection import DebtInput, FlowInput, ProjectionInput, fi_number, monte_carlo, project, simulate


def flat(**overrides) -> ProjectionInput:
    """No inflation, no returns, no taxes: makes cash-flow math easy to check by hand."""
    base = dict(
        current_age=40,
        retirement_age=65,
        life_expectancy=45,
        start_year=2026,
        inflation=0.0,
        expected_return=0.0,
        retirement_return=0.0,
        return_volatility=0.0,
        cash_return=0.0,
        tax_mode="flat",
        effective_tax_rate=0.0,
    )
    base.update(overrides)
    return ProjectionInput(**base)


def test_surplus_is_invested_in_taxable():
    inp = flat(
        flows=[
            FlowInput("Salary", "income", 100_000, 40, 64),
            FlowInput("Living", "expense", 60_000, 40, 95),
        ]
    )
    rows = simulate(inp)
    assert [r.age for r in rows] == [40, 41, 42, 43, 44, 45]
    assert rows[0].taxable == pytest.approx(40_000)
    assert rows[-1].taxable == pytest.approx(240_000)
    assert all(r.shortfall == 0 for r in rows)


def test_withdrawal_order_and_depletion():
    inp = flat(cash=50_000, taxable=50_000, flows=[FlowInput("Living", "expense", 40_000, 40, 95)])
    rows = simulate(inp)
    assert rows[0].cash == pytest.approx(10_000)
    assert rows[1].cash == 0 and rows[1].taxable == pytest.approx(20_000)
    assert rows[2].shortfall == pytest.approx(20_000)
    assert project(inp, simulations=0)["depletion_age"] == 42


def test_tax_deferred_withdrawals_are_grossed_up():
    inp = flat(
        current_age=62, retirement_age=62, life_expectancy=63, effective_tax_rate=0.15, tax_deferred=100_000,
        flows=[FlowInput("Living", "expense", 8_500, 62, 95)],
    )
    row = simulate(inp)[0]
    assert row.withdrawals == pytest.approx(10_000, abs=1)
    assert row.taxes == pytest.approx(1_500, abs=1)
    assert row.tax_deferred == pytest.approx(90_000, abs=1)
    assert row.shortfall == 0


def test_early_withdrawals_pay_penalty():
    inp = flat(tax_deferred=100_000, flows=[FlowInput("Living", "expense", 9_000, 40, 95)])
    row = simulate(inp)[0]
    assert row.tax_penalty == pytest.approx(1_000, abs=1)
    assert row.withdrawals == pytest.approx(10_000, abs=1)


def test_progressive_withdrawal_covers_need_exactly():
    inp = flat(
        current_age=66, retirement_age=65, life_expectancy=67, tax_mode="progressive", state_tax_rate=0.05,
        tax_deferred=2_000_000, flows=[FlowInput("Living", "expense", 120_000, 66, 95)],
    )
    row = simulate(inp)[0]
    assert row.shortfall == 0
    assert row.withdrawals - row.taxes == pytest.approx(120_000, abs=1)
    assert row.tax_federal > 0 and row.tax_state > 0 and row.tax_fica == 0


def test_rmds_are_forced_and_reinvested():
    inp = flat(current_age=80, retirement_age=65, life_expectancy=80, start_year=2026, tax_deferred=202_000)
    row = simulate(inp)[0]  # born 1946 -> RMDs started at 72; divisor at 80 is 20.2
    assert row.rmd == pytest.approx(10_000)
    assert row.taxable == pytest.approx(10_000)
    assert row.tax_deferred == pytest.approx(192_000)


def test_taxable_withdrawals_realize_gains_and_reduce_basis():
    inp = flat(
        current_age=62, retirement_age=62, life_expectancy=62, effective_tax_rate=0.2,
        taxable=100_000, taxable_basis=50_000, flows=[FlowInput("Living", "expense", 20_000, 62, 95)],
    )
    row = simulate(inp)[0]
    assert row.withdrawals == pytest.approx(20_000 / 0.9, abs=1)
    assert row.realized_gains == pytest.approx(row.withdrawals / 2, abs=1)
    assert row.taxes == pytest.approx(0.2 * row.realized_gains, abs=1)
    assert row.taxable_basis == pytest.approx(50_000 - row.withdrawals / 2, abs=1)
    assert row.shortfall == 0


def test_surplus_adds_to_basis():
    inp = flat(taxable=10_000, taxable_basis=5_000, flows=[FlowInput("Salary", "income", 1_000, 40, 95)])
    assert simulate(inp)[0].taxable_basis == pytest.approx(6_000)


def test_roth_conversion_fills_bracket():
    inp = flat(
        current_age=66, retirement_age=65, life_expectancy=66, start_year=2026, tax_mode="progressive",
        tax_deferred=1_000_000, cash=100_000, roth_conversion_rate=0.12,
    )
    row = simulate(inp)[0]
    assert row.roth_conversion == pytest.approx(50_400 + 16_100 + 2_050, abs=1)
    assert row.tax_federal == pytest.approx(1_240 + 38_000 * 0.12, abs=1)
    assert row.tax_free == pytest.approx(row.roth_conversion)
    assert row.cash == pytest.approx(100_000 - row.taxes)


def test_roth_conversions_stop_before_rmds():
    inp = flat(current_age=75, retirement_age=65, life_expectancy=75, start_year=2026, tax_mode="progressive",
               tax_deferred=500_000, cash=100_000, roth_conversion_rate=0.22)
    assert simulate(inp)[0].roth_conversion == 0


def test_recurring_expense_every_n_years():
    inp = flat(cash=200_000, flows=[FlowInput("Car", "expense", 30_000, 40, 95, category="transportation", every_n_years=3)])
    rows = simulate(inp)
    assert [r.expenses for r in rows] == [30_000, 0, 0, 30_000, 0, 0]
    assert rows[0].expenses_by_category_real == {"transportation": 30_000}


def test_contributions_stop_at_retirement_and_reduce_taxable_income():
    inp = flat(
        retirement_age=42,
        effective_tax_rate=0.2,
        contrib_tax_deferred=10_000,
        flows=[FlowInput("Salary", "income", 50_000, 40, 41)],
    )
    rows = simulate(inp)
    assert rows[0].taxes == pytest.approx(8_000)
    assert rows[0].tax_deferred == pytest.approx(10_000)
    assert rows[2].contributions == 0


def test_inflation_and_real_values():
    inp = flat(inflation=0.10, cash=0, flows=[FlowInput("Gift", "income", 1_000, 41, 41, tax_type="tax_free")])
    rows = simulate(inp)
    assert rows[1].income == pytest.approx(1_100)
    assert rows[1].investable_real == pytest.approx(1_100 / 1.21)


def test_debt_amortizes():
    inp = flat(debts=[DebtInput("Car", 10_000, 0.0, 500)])
    rows = simulate(inp)
    assert rows[0].liabilities == pytest.approx(4_000)
    assert rows[1].liabilities == 0
    assert rows[1].debt_payments == pytest.approx(4_000)


def test_goals_are_reported():
    inp = flat(cash=100_000, flows=[FlowInput("House down payment", "goal", 60_000, 42, 42)])
    rows = simulate(inp)
    assert rows[2].goals == pytest.approx(60_000)
    assert rows[2].goal_names == ["House down payment"]


def test_fi_number_and_age():
    inp = flat(
        life_expectancy=60,
        withdrawal_rate=0.04,
        flows=[
            FlowInput("Salary", "income", 300_000, 40, 64),
            FlowInput("Living", "expense", 40_000, 40, 95),
        ],
    )
    assert fi_number(inp) == pytest.approx(1_000_000)
    assert project(inp, simulations=0)["fi_age"] == 43  # 260k/yr saved -> 1.04M after 4 years


def test_monte_carlo_without_volatility_matches_deterministic():
    good = flat(cash=1_000_000, flows=[FlowInput("Living", "expense", 10_000, 40, 95)])
    bad = flat(cash=10_000, flows=[FlowInput("Living", "expense", 10_000, 40, 95)])
    assert monte_carlo(good, simulations=20)["success_rate"] == 1.0
    assert monte_carlo(bad, simulations=20)["success_rate"] == 0.0


def test_monte_carlo_is_reproducible_with_seed():
    inp = flat(
        life_expectancy=90,
        expected_return=0.07,
        retirement_return=0.05,
        return_volatility=0.15,
        taxable=800_000,
        retirement_age=40,
        flows=[FlowInput("Living", "expense", 40_000, 40, 95)],
    )
    a = monte_carlo(inp, simulations=200, seed=7)
    b = monte_carlo(inp, simulations=200, seed=7)
    assert a == b
    assert 0 < a["success_rate"] < 1
    band = a["bands"][10]
    assert band["p10"] <= band["p50"] <= band["p90"]

import random
import statistics
from dataclasses import replace

import pytest

from app.finance.historical_data import ANNUAL_RETURNS
from app.finance.projection import (
    FlowInput,
    ProjectionInput,
    _mean_return,
    backtest,
    historical_paths,
    random_returns,
    simulate,
    stock_allocation,
)


def alloc(**overrides) -> ProjectionInput:
    base = dict(
        current_age=40, retirement_age=60, life_expectancy=90, start_year=2026, return_model="allocation",
        stock_return=0.08, bond_return=0.04, stock_allocation_now=0.9, stock_allocation_retired=0.5,
    )
    base.update(overrides)
    return ProjectionInput(**base)


def test_glide_path_is_linear_until_retirement():
    inp = alloc()
    assert stock_allocation(inp, 40) == pytest.approx(0.9)
    assert stock_allocation(inp, 50) == pytest.approx(0.7)
    assert stock_allocation(inp, 60) == pytest.approx(0.5)
    assert stock_allocation(inp, 80) == pytest.approx(0.5)
    assert _mean_return(inp, 50) == pytest.approx(0.7 * 0.08 + 0.3 * 0.04)
    assert stock_allocation(alloc(return_model="simple"), 50) is None


def test_glide_path_ends_when_first_spouse_retires():
    inp = alloc(spouse_current_age=45, spouse_retirement_age=60)  # spouse retires at your 55
    assert stock_allocation(inp, 55) == pytest.approx(0.5)
    assert stock_allocation(inp, 50) == pytest.approx(0.9 - 0.4 * 10 / 15)


def test_already_retired_uses_retired_allocation():
    inp = alloc(current_age=70)
    assert stock_allocation(inp, 70) == pytest.approx(0.5)


def test_correlated_draws_match_inputs():
    inp = alloc(current_age=0, retirement_age=0, life_expectancy=19_999, stock_allocation_retired=1.0,
                stock_volatility=0.2)
    stocks = random_returns(inp, random.Random(1))
    assert statistics.mean(stocks) == pytest.approx(0.08, abs=0.005)
    assert statistics.stdev(stocks) == pytest.approx(0.2, abs=0.005)

    bonds_only = alloc(current_age=0, retirement_age=0, life_expectancy=19_999, stock_allocation_retired=0.0,
                       bond_volatility=0.05, stock_bond_correlation=0.5)
    bonds = random_returns(bonds_only, random.Random(1))
    assert statistics.stdev(bonds) == pytest.approx(0.05, abs=0.002)
    # Same seed -> same stock shocks, so the bond path correlates with the stock path at rho.
    assert statistics.correlation(stocks, bonds) == pytest.approx(0.5, abs=0.03)


def test_historical_paths_convert_real_returns_to_plan_inflation():
    inp = alloc(current_age=60, retirement_age=60, life_expectancy=62, inflation=0.02, stock_allocation_retired=1.0)
    data = ((2000, 0.10, 0.0, 0.0), (2001, 0.21, 0.0, 0.10), (2002, 0.0, 0.0, 0.0), (2003, 0.05, 0.0, 0.0))
    paths = historical_paths(inp, data)
    assert [year for year, _ in paths] == [2000, 2001]
    # 2001: 21% nominal with 10% CPI is 10% real, re-inflated at 2%.
    assert paths[0][1] == pytest.approx([0.122, 0.122, 0.02])
    assert backtest(alloc(life_expectancy=200), data) is None


def test_backtest_on_real_history():
    inp = alloc(current_age=55, retirement_age=55, life_expectancy=84, tax_mode="flat", effective_tax_rate=0.0,
                taxable=1_000_000, taxable_basis=1_000_000,
                flows=[FlowInput("Spending", "expense", 40_000, 55, 84)])
    result = backtest(inp)
    assert result["simulations"] == len(ANNUAL_RETURNS) - 30 + 1
    assert result["first_year"] == 1928
    assert 0.8 <= result["success_rate"] <= 1.0  # 4% rule, 60/40, 30 years
    assert result["worst_start_year"] in {s["start_year"] for s in result["starts"]}
    broke = backtest(replace(inp, taxable=300_000, taxable_basis=300_000))
    assert broke["success_rate"] < 0.2
    worst = next(s for s in broke["starts"] if s["start_year"] == broke["worst_start_year"])
    assert worst["depletion_age"] == min(s["depletion_age"] for s in broke["starts"] if s["depletion_age"])


def test_rows_report_allocation():
    rows = simulate(alloc(life_expectancy=61, cash=1_000))
    assert rows[0].stock_allocation == pytest.approx(0.9)
    assert rows[-1].stock_allocation == pytest.approx(0.5)

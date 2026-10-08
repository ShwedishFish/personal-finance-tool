import random
import statistics

import pytest

from app.finance.projection import ProjectionInput, _mean_return, random_returns, simulate, stock_allocation


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


def test_rows_report_allocation():
    rows = simulate(alloc(life_expectancy=61, cash=1_000))
    assert rows[0].stock_allocation == pytest.approx(0.9)
    assert rows[-1].stock_allocation == pytest.approx(0.5)

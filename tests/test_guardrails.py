import pytest

from app.finance.projection import FlowInput, ProjectionInput, monte_carlo, simulate


def plan(**overrides) -> ProjectionInput:
    base = dict(
        current_age=60, retirement_age=60, life_expectancy=95, start_year=2026, inflation=0.0,
        tax_mode="flat", effective_tax_rate=0.0, taxable=1_000_000, guardrails=True,
        flows=[
            FlowInput("Living", "expense", 40_000, 60, 95),
            FlowInput("Rent", "expense", 10_000, 60, 95, category="housing"),
        ],
    )
    base.update(overrides)
    return ProjectionInput(**base)


def flat(n: int, *early: float) -> list[float]:
    return list(early) + [0.0] * (n - len(early))


def test_crash_cuts_flexible_spending_only():
    rows = simulate(plan(), flat(36, -0.3, -0.3))
    # Starting rate 5%; after each crash the rate stays above 6%, so cuts repeat until it is back inside.
    assert [round(r.spending_adjustment, 3) for r in rows[:5]] == [1.0, 0.9, 0.81, 0.729, 0.7]
    assert rows[1].expenses == pytest.approx(10_000 + 40_000 * 0.9)


def test_boom_raises_spending_and_floor_limits_cuts():
    rows = simulate(plan(), flat(36, 0.5, 0.5))
    assert [round(r.spending_adjustment, 3) for r in rows[:3]] == [1.0, 1.1, 1.21]
    crash = simulate(plan(guardrail_floor=0.85), flat(36, -0.5, -0.5, -0.5))
    assert min(r.spending_adjustment for r in crash) == pytest.approx(0.85)


def test_no_cuts_in_final_years_and_off_by_default():
    late = simulate(plan(current_age=85, retirement_age=85, life_expectancy=95), flat(11, -0.5, -0.5))
    assert all(r.spending_adjustment == 1.0 for r in late)
    off = simulate(plan(guardrails=False), flat(36, -0.3, -0.3))
    assert all(r.spending_adjustment == 1.0 for r in off)


def test_guardrails_wait_until_everyone_is_retired():
    rows = simulate(plan(current_age=55, flows=[FlowInput("Living", "expense", 40_000, 55, 95)]), flat(41, -0.4, -0.4))
    assert all(r.spending_adjustment == 1.0 for r in rows if not r.retired)


def test_guardrails_raise_monte_carlo_success():
    tight = plan(taxable=800_000, return_model="allocation")
    without = monte_carlo(plan(taxable=800_000, return_model="allocation", guardrails=False), 300)
    with_rails = monte_carlo(tight, 300)
    assert with_rails["success_rate"] > without["success_rate"]
    assert with_rails["lowest_spending_p10"] < 1.0
    assert without["lowest_spending_p10"] == 1.0

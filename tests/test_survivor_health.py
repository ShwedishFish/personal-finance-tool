from datetime import date
from types import SimpleNamespace

import pytest

from app.finance.medicare import IRMAA_ANNUAL_SURCHARGE, irmaa_surcharge, irmaa_tier
from app.finance.projection import FlowInput, ProjectionInput, simulate
from app.services import healthcare_flows


def couple(**overrides) -> ProjectionInput:
    base = dict(
        current_age=70, retirement_age=65, life_expectancy=75, start_year=2026,
        inflation=0.0, expected_return=0.0, retirement_return=0.0, return_volatility=0.0, cash_return=0.0,
        tax_mode="flat", effective_tax_rate=0.0, filing_status="married_joint",
        spouse_current_age=70, spouse_life_expectancy=80, survivor_spending=0.75, cash=5_000_000,
    )
    base.update(overrides)
    return ProjectionInput(**base)


def test_irmaa_tiers():
    assert irmaa_tier(109_000, "single") == 0
    assert irmaa_tier(109_001, "single") == 1
    assert irmaa_tier(499_999, "single") == 4
    assert irmaa_tier(500_000, "single") == 5
    assert irmaa_tier(218_001, "married_joint") == 1
    assert irmaa_tier(218_001, "married_joint", scale=1.1) == 0
    assert irmaa_surcharge(300_000, "single", 1) == pytest.approx(IRMAA_ANNUAL_SURCHARGE[3])
    assert irmaa_surcharge(300_000, "married_joint", 2) == pytest.approx(IRMAA_ANNUAL_SURCHARGE[1] * 2)


def test_irmaa_uses_income_from_two_years_earlier():
    inp = ProjectionInput(
        current_age=66, retirement_age=65, life_expectancy=69, start_year=2026,
        inflation=0.0, expected_return=0.0, retirement_return=0.0, return_volatility=0.0, cash_return=0.0,
        cash=1_000_000, flows=[FlowInput("Bonus", "income", 300_000, 66, 66, tax_type="ordinary")],
    )
    rows = simulate(inp)
    # Year 0 has no history and is estimated from this year's income; year 1 sees no income;
    # year 2 is billed on year 0's income.
    assert [r.irmaa for r in rows] == pytest.approx([IRMAA_ANNUAL_SURCHARGE[3], 0, IRMAA_ANNUAL_SURCHARGE[3], 0])
    assert rows[0].expenses_by_category_real["healthcare"] == pytest.approx(IRMAA_ANNUAL_SURCHARGE[3])


def test_plan_runs_until_second_death_with_survivor_rules():
    inp = couple(
        flows=[
            FlowInput("SS", "income", 40_000, 70, 80, tax_type="social_security", owner="self"),
            FlowInput("SS (spouse)", "income", 15_000, 70, 80, tax_type="social_security", owner="spouse"),
            FlowInput("Spousal (spouse)", "income", 5_000, 70, 80, tax_type="social_security", owner="spouse",
                      spousal=True),
            FlowInput("Living", "expense", 80_000, 70, 80),
            FlowInput("Grandkid tuition", "expense", 10_000, 70, 80, category="education"),
            FlowInput("Medicare", "expense", 7_000, 70, 80, category="healthcare", owner="self"),
        ]
    )
    rows = simulate(inp)
    assert inp.end_age == 80 and rows[-1].age == 80
    before, after = rows[5], rows[6]  # you die after age 75
    assert before.self_alive and before.filing_status == "married_joint"
    assert before.income == pytest.approx(60_000)
    assert before.expenses == pytest.approx(97_000)
    assert not after.self_alive and after.spouse_alive and after.filing_status == "single"
    assert after.income == pytest.approx(40_000)  # survivor keeps the larger benefit; spousal top-up ends
    assert after.expenses == pytest.approx(80_000 * 0.75 + 10_000)


def test_survivor_rmds_use_the_survivors_age():
    inp = couple(current_age=80, life_expectancy=80, spouse_current_age=60, spouse_life_expectancy=62,
                 tax_deferred=1_000_000, cash=0)
    rows = simulate(inp)
    assert rows[0].rmd > 0
    assert rows[1].rmd == 0 and rows[1].spouse_age == 61


def test_healthcare_flows_by_person():
    year = date.today().year
    plan = SimpleNamespace(
        birth_year=year - 55, spouse_birth_year=year - 53, life_expectancy=95, spouse_life_expectancy=95,
        pre_medicare_cost=12_000, medicare_cost=7_000, health_cost_growth=0.02,
    )
    flows = {f.name: f for f in healthcare_flows(plan, current_age=55, retirement_age=60)}
    assert (flows["Health insurance before Medicare"].start_age, flows["Health insurance before Medicare"].end_age) == (60, 64)
    assert (flows["Health insurance before Medicare (spouse)"].start_age,
            flows["Health insurance before Medicare (spouse)"].end_age) == (60, 66)
    assert flows["Medicare premiums & out-of-pocket"].start_age == 65
    assert flows["Medicare premiums & out-of-pocket (spouse)"].start_age == 67
    assert flows["Medicare premiums & out-of-pocket (spouse)"].end_age == 97
    assert all(f.category == "healthcare" and f.real_growth == 0.02 for f in flows.values())
    assert flows["Medicare premiums & out-of-pocket (spouse)"].owner == "spouse"


def test_retirement_age_explorer(client):
    year = date.today().year
    client.post("/api/accounts", json={"name": "401k", "kind": "retirement", "tax_treatment": "tax_deferred",
                                       "balance": 900_000, "annual_contribution": 20_000})
    plan = client.post("/api/plans", json={"name": "P", "birth_year": year - 55, "retirement_age": 62}).json()
    for cf in [
        {"name": "Salary", "kind": "income", "amount": 120_000, "ends_at_retirement": True},
        {"name": "Living", "kind": "expense", "amount": 60_000},
    ]:
        client.post(f"/api/plans/{plan['id']}/cash-flows", json=cf)
    r = client.get(f"/api/plans/{plan['id']}/retirement-ages?simulations=100").json()
    ages = [o["retirement_age"] for o in r["options"]]
    assert ages == list(range(57, 57 + len(ages))) and 11 <= len(ages) <= 16
    if len(ages) > 11:  # extended past +5 years only to find an age that meets the target
        assert r["earliest_age"] == ages[-1] or r["earliest_age"] is None
    rates = [o["success_rate"] for o in r["options"]]
    assert rates[-1] >= rates[0]
    if r["earliest_age"] is not None:
        hit = next(o for o in r["options"] if o["retirement_age"] == r["earliest_age"])
        assert hit["success_rate"] >= r["target"]
        assert all(o["success_rate"] < r["target"] for o in r["options"] if o["retirement_age"] < r["earliest_age"])

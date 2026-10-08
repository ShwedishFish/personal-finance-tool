import pytest

from app.finance.state_tax import STATES, bracket_tax, state_income_tax
from app.finance.tax import TaxProfile, YearIncome, income_tax


def tax(code, filing="single", *, other=0.0, ss=0.0, agi=None, gains=0.0, retirement=0.0, over_65=0, scale=1.0):
    return state_income_tax(
        code, filing, other_income=other, social_security_taxable=ss,
        federal_agi=other + ss + gains if agi is None else agi, capital_gains=gains,
        retirement_withdrawals=retirement, people_65_plus=over_65, scale=scale,
    )


def test_table_covers_every_state_and_dc():
    assert len(STATES) == 51
    for code, state in STATES.items():
        for brackets in (state.single, state.married or ()):
            thresholds = [over for over, _ in brackets]
            assert thresholds == sorted(thresholds), code


def test_california_brackets_deduction_and_credit():
    expected = bracket_tax(100_000 - 5_540, STATES["CA"].single) - 153
    assert tax("CA", other=100_000) == pytest.approx(expected)
    # 1% to 11,079, 2% to 26,264, 4% to 41,452, 6% to 57,542, 8% to 72,724, then 9.3%.
    manual = 11_079 * .01 + 15_185 * .02 + 15_188 * .04 + 16_090 * .06 + 15_182 * .08 + (94_460 - 72_724) * .093
    assert expected + 153 == pytest.approx(manual)
    assert tax("CA", other=200_000, scale=2.0) == pytest.approx(2 * tax("CA", other=100_000))


def test_no_tax_states_and_washington_capital_gains():
    assert tax("TX", other=500_000, gains=500_000) == 0
    assert tax("WA", other=500_000) == 0
    assert tax("WA", gains=300_000) == pytest.approx(22_000 * 0.07)


def test_retirement_income_exclusions():
    assert tax("PA", other=50_000, retirement=50_000) == 0
    assert tax("PA", other=50_000) == pytest.approx(50_000 * 0.0307)
    both_65 = tax("GA", "married_joint", other=130_000, retirement=130_000, over_65=2)
    assert both_65 == 0
    one_65 = tax("GA", "married_joint", other=130_000, retirement=130_000, over_65=1)  # 65k + 35k excluded
    assert one_65 == pytest.approx((30_000 - 24_000) * 0.0519)
    assert tax("NY", other=20_000, retirement=20_000) == 0


def test_social_security_rules():
    assert tax("IL", ss=30_000) == 0  # exempt everywhere but eight states
    assert tax("MN", ss=30_000) == pytest.approx((30_000 - 15_300) * 0.0535)
    assert tax("VT", ss=20_000, agi=50_000) == 0  # under Vermont's full-exemption AGI
    assert tax("VT", ss=20_000, agi=80_000) > 0
    assert tax("CO", ss=40_000, over_65=1) == 0
    assert tax("CO", ss=40_000) == pytest.approx((40_000 - 16_100) * 0.044)


def test_missouri_exempts_capital_gains_and_first_dollars_untaxed():
    assert tax("MO", gains=100_000) == 0
    assert tax("OH", other=26_050 + 2_400) == 0
    assert tax("OH", other=40_000) == pytest.approx((40_000 - 2_400 - 26_050) * 0.0275)


def test_federal_calculation_uses_chosen_state():
    y = YearIncome(wages=150_000, capital_gains=20_000)
    chosen = income_tax(TaxProfile(state="NY"), y)
    assert chosen.state == pytest.approx(tax("NY", other=150_000, gains=20_000))
    flat = income_tax(TaxProfile(state_rate=0.05), y)
    assert flat.state > 0 and flat.federal == pytest.approx(chosen.federal)


def test_plan_state_api(client):
    states = client.get("/api/states").json()
    assert states["CA"] == "California" and len(states) == 51
    plan = client.post("/api/plans", json={"name": "S", "birth_year": 1980}).json()
    assert client.patch(f"/api/plans/{plan['id']}", json={"state": "ca"}).json()["state"] == "CA"
    assert client.patch(f"/api/plans/{plan['id']}", json={"state": "ZZ"}).status_code == 422

import pytest

from app.finance.social_security import claiming_factor, full_retirement_age_months, spousal_factor, spousal_top_up
from app.finance.tax import (
    TaxProfile,
    YearIncome,
    bracket_ceiling,
    bracket_tax,
    capital_gains_tax,
    income_tax,
    payroll_tax,
    required_minimum_distribution,
    rmd_start_age,
    taxable_social_security,
)


def test_bracket_tax_single():
    assert bracket_tax(12_400, "single") == pytest.approx(1_240)
    assert bracket_tax(50_400, "single") == pytest.approx(1_240 + 38_000 * 0.12)
    assert bracket_tax(0, "single") == 0


def test_brackets_scale_with_inflation():
    assert bracket_tax(24_800, "single", scale=2.0) == pytest.approx(2_480)


def test_payroll_tax_caps_social_security_portion():
    assert payroll_tax(100_000, "single") == pytest.approx(7_650)
    assert payroll_tax(300_000, "single") == pytest.approx(184_500 * 0.062 + 300_000 * 0.0145 + 100_000 * 0.009)


def test_social_security_taxation_tiers():
    assert taxable_social_security(10_000, 20_000, "single") == 0
    assert taxable_social_security(20_000, 20_000, "single") == pytest.approx(2_500)
    assert taxable_social_security(200_000, 30_000, "single") == pytest.approx(0.85 * 30_000)


def test_income_tax_progressive_with_standard_deduction():
    tax = income_tax(
        TaxProfile(mode="progressive", filing_status="married_joint", state_rate=0.05), YearIncome(wages=132_200)
    )
    taxable_income = 100_000
    assert tax.federal == pytest.approx(bracket_tax(taxable_income, "married_joint"))
    assert tax.state == pytest.approx(5_000)
    assert tax.fica == pytest.approx(132_200 * 0.0765)


def test_capital_gains_stack_on_ordinary_income():
    assert capital_gains_tax(40_000, 20_000, "single") == pytest.approx(10_550 * 0.15)
    assert capital_gains_tax(600_000, 10_000, "single") == pytest.approx(2_000)
    assert capital_gains_tax(0, 49_450, "single") == 0


def test_niit_and_unused_deduction_shelters_gains():
    profile = TaxProfile(mode="progressive", filing_status="single")
    sheltered = income_tax(profile, YearIncome(capital_gains=10_000))
    assert sheltered.federal == 0
    high = income_tax(profile, YearIncome(ordinary=190_000, capital_gains=30_000))
    ordinary_ti = 190_000 - 16_100
    expected = bracket_tax(ordinary_ti, "single") + capital_gains_tax(ordinary_ti, 30_000, "single") + 20_000 * 0.038
    assert high.federal == pytest.approx(expected)


def test_bracket_ceiling():
    assert bracket_ceiling(0.12, "single") == 50_400
    assert bracket_ceiling(0.22, "married_joint", scale=2) == 422_800
    with pytest.raises(ValueError):
        bracket_ceiling(0.15, "single")


def test_spousal_benefits():
    assert spousal_factor(1990, 62) == pytest.approx(0.65)
    assert spousal_factor(1990, 67) == 1 and spousal_factor(1990, 70) == 1
    assert spousal_top_up(0, 2_000, 1990, 67) == pytest.approx(12_000)
    assert spousal_top_up(1_200, 2_000, 1990, 67) == 0


def test_rmd_start_ages_and_amounts():
    assert rmd_start_age(1950) == 72 and rmd_start_age(1955) == 73 and rmd_start_age(1962) == 75
    assert required_minimum_distribution(100_000, 74, 1962) == 0
    assert required_minimum_distribution(246_000, 75, 1962) == pytest.approx(10_000)


def test_full_retirement_age():
    assert full_retirement_age_months(1950) == 66 * 12
    assert full_retirement_age_months(1957) == 66 * 12 + 6
    assert full_retirement_age_months(1990) == 67 * 12


@pytest.mark.parametrize("age, factor", [(62, 0.70), (64, 0.80), (65, 0.8667), (67, 1.0), (70, 1.24)])
def test_claiming_factor_fra_67(age, factor):
    assert claiming_factor(1990, age) == pytest.approx(factor, abs=1e-4)

"""US federal income tax, payroll tax, Social Security taxation, and RMDs.

Dollar thresholds are 2026 values. Inflation-indexed thresholds are scaled by the
simulation's inflation factor; thresholds the law does not index (Social Security
provisional income, additional Medicare tax) are not.
"""

from dataclasses import dataclass

BRACKET_RATES = (0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37)
BRACKET_TOPS = {
    "single": (12_400, 50_400, 105_700, 201_775, 256_225, 640_600),
    "married_joint": (24_800, 100_800, 211_400, 403_550, 512_450, 768_700),
}
STANDARD_DEDUCTION = {"single": 16_100, "married_joint": 32_200}
AGE_65_EXTRA_DEDUCTION = {"single": 2_050, "married_joint": 1_650}  # per person 65+

SS_WAGE_BASE = 184_500
SS_RATE = 0.062
MEDICARE_RATE = 0.0145
ADDITIONAL_MEDICARE_RATE = 0.009
ADDITIONAL_MEDICARE_THRESHOLD = {"single": 200_000, "married_joint": 250_000}

SS_PROVISIONAL_THRESHOLDS = {"single": (25_000, 34_000), "married_joint": (32_000, 44_000)}

EARLY_WITHDRAWAL_AGE = 60  # 59½, rounded to the first full year without penalty
EARLY_WITHDRAWAL_PENALTY = 0.10

# IRS Uniform Lifetime Table (2022+), distribution period by age.
UNIFORM_LIFETIME = {
    72: 27.4, 73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9, 78: 22.0, 79: 21.1, 80: 20.2,
    81: 19.4, 82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2, 87: 14.4, 88: 13.7, 89: 12.9,
    90: 12.2, 91: 11.5, 92: 10.8, 93: 10.1, 94: 9.5, 95: 8.9, 96: 8.4, 97: 7.8, 98: 7.3, 99: 6.8,
    100: 6.4, 101: 6.0, 102: 5.6, 103: 5.2, 104: 4.9, 105: 4.6, 106: 4.3, 107: 4.1, 108: 3.9,
    109: 3.7, 110: 3.5, 111: 3.4, 112: 3.3, 113: 3.1, 114: 3.0, 115: 2.9, 116: 2.8, 117: 2.7,
    118: 2.5, 119: 2.3, 120: 2.0,
}


@dataclass
class TaxBreakdown:
    federal: float = 0.0
    state: float = 0.0
    fica: float = 0.0
    penalty: float = 0.0

    @property
    def total(self) -> float:
        return self.federal + self.state + self.fica + self.penalty


def bracket_tax(taxable_income: float, filing_status: str, scale: float = 1.0) -> float:
    tax = 0.0
    lower = 0.0
    for rate, top in zip(BRACKET_RATES, BRACKET_TOPS[filing_status] + (float("inf"),)):
        upper = top * scale
        if taxable_income <= lower:
            break
        tax += (min(taxable_income, upper) - lower) * rate
        lower = upper
    return tax


def standard_deduction(filing_status: str, scale: float = 1.0, people_65_plus: int = 0) -> float:
    return (STANDARD_DEDUCTION[filing_status] + AGE_65_EXTRA_DEDUCTION[filing_status] * people_65_plus) * scale


def payroll_tax(wages: float, filing_status: str, scale: float = 1.0) -> float:
    """Employee share of Social Security and Medicare tax on wages."""
    if wages <= 0:
        return 0.0
    ss = min(wages, SS_WAGE_BASE * scale) * SS_RATE
    medicare = wages * MEDICARE_RATE
    extra = max(0.0, wages - ADDITIONAL_MEDICARE_THRESHOLD[filing_status]) * ADDITIONAL_MEDICARE_RATE
    return ss + medicare + extra


def taxable_social_security(other_income: float, benefits: float, filing_status: str) -> float:
    """Portion of Social Security benefits included in taxable income (IRS Pub. 915 worksheet)."""
    if benefits <= 0:
        return 0.0
    base, upper = SS_PROVISIONAL_THRESHOLDS[filing_status]
    provisional = other_income + 0.5 * benefits
    if provisional <= base:
        return 0.0
    if provisional <= upper:
        return min(0.5 * benefits, 0.5 * (provisional - base))
    tier1 = min(0.5 * benefits, 0.5 * (upper - base))
    return min(0.85 * benefits, 0.85 * (provisional - upper) + tier1)


def rmd_start_age(birth_year: int) -> int:
    if birth_year >= 1960:
        return 75
    if birth_year >= 1951:
        return 73
    return 72


def required_minimum_distribution(balance: float, age: int, birth_year: int) -> float:
    if balance <= 0 or age < rmd_start_age(birth_year):
        return 0.0
    return balance / UNIFORM_LIFETIME.get(age, UNIFORM_LIFETIME[120])


@dataclass
class TaxProfile:
    mode: str = "progressive"  # "progressive" | "flat"
    filing_status: str = "single"
    flat_rate: float = 0.15
    state_rate: float = 0.0


def income_tax(
    profile: TaxProfile,
    *,
    wages: float,
    ordinary: float,
    social_security: float,
    pre_tax_contributions: float,
    deferred_withdrawals: float,
    early_withdrawals: float,
    scale: float,
    people_65_plus: int,
) -> TaxBreakdown:
    """Total tax for one year. `deferred_withdrawals` includes RMDs; `early_withdrawals` is the penalized part."""
    other = max(0.0, wages - pre_tax_contributions) + ordinary + deferred_withdrawals
    ss_taxable = taxable_social_security(other, social_security, profile.filing_status)
    penalty = early_withdrawals * EARLY_WITHDRAWAL_PENALTY

    if profile.mode == "flat":
        return TaxBreakdown(federal=profile.flat_rate * (other + ss_taxable), penalty=penalty)

    taxable_income = max(
        0.0, other + ss_taxable - standard_deduction(profile.filing_status, scale, people_65_plus)
    )
    return TaxBreakdown(
        federal=bracket_tax(taxable_income, profile.filing_status, scale),
        state=profile.state_rate * taxable_income,
        fica=payroll_tax(wages, profile.filing_status, scale),
        penalty=penalty,
    )

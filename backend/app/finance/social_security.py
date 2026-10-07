"""Social Security retirement benefit adjustments for claiming age.

Benefits are entered as the monthly amount at full retirement age (the "PIA" shown on an
ssa.gov statement) in today's dollars. Cost-of-living adjustments keep them constant in
real terms, so the projection inflates them like any other flow.
"""

EARLIEST_CLAIM_AGE = 62
LATEST_CLAIM_AGE = 70


def full_retirement_age_months(birth_year: int) -> int:
    if birth_year <= 1937:
        return 65 * 12
    if birth_year <= 1942:
        return 65 * 12 + (birth_year - 1937) * 2
    if birth_year <= 1954:
        return 66 * 12
    if birth_year <= 1959:
        return 66 * 12 + (birth_year - 1954) * 2
    return 67 * 12


def claiming_factor(birth_year: int, claim_age: int) -> float:
    """Multiplier on the full-retirement-age benefit when claiming at `claim_age` (whole years)."""
    claim_months = min(max(claim_age, EARLIEST_CLAIM_AGE), LATEST_CLAIM_AGE) * 12
    fra = full_retirement_age_months(birth_year)
    diff = claim_months - fra
    if diff >= 0:
        return 1 + diff * (2 / 3) / 100
    early = -diff
    first = min(early, 36)
    rest = early - first
    return 1 - first * (5 / 9) / 100 - rest * (5 / 12) / 100


def annual_benefit(monthly_at_fra: float, birth_year: int, claim_age: int) -> float:
    return monthly_at_fra * 12 * claiming_factor(birth_year, claim_age)


def spousal_factor(birth_year: int, claim_age: int) -> float:
    """Spousal benefits shrink when claimed early but earn no delayed credits after full retirement age."""
    early = max(0, full_retirement_age_months(birth_year) - max(claim_age, EARLIEST_CLAIM_AGE) * 12)
    first = min(early, 36)
    return 1 - first * (25 / 36) / 100 - (early - first) * (5 / 12) / 100


def spousal_top_up(own_monthly_at_fra: float, partner_monthly_at_fra: float, birth_year: int, claim_age: int) -> float:
    """Yearly amount added to a person's own benefit, up to half of their partner's full benefit."""
    excess = max(0.0, 0.5 * partner_monthly_at_fra - own_monthly_at_fra)
    return excess * 12 * spousal_factor(birth_year, claim_age)

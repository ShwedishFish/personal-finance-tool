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

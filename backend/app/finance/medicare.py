"""Medicare income-related monthly adjustment amounts (IRMAA), 2026.

IRMAA is a surcharge on Part B and Part D premiums for each person on Medicare, set by
modified adjusted gross income from two years earlier.
"""

MEDICARE_AGE = 65
IRMAA_LOOKBACK_YEARS = 2

# MAGI floors of each surcharge tier, and the yearly Part B + Part D surcharge per person.
IRMAA_FLOORS = {
    "single": (109_000, 137_000, 171_000, 205_000, 500_000),
    "married_joint": (218_000, 274_000, 342_000, 410_000, 750_000),
}
IRMAA_ANNUAL_SURCHARGE = tuple(
    round((part_b + part_d) * 12, 2)
    for part_b, part_d in ((81.20, 14.50), (202.90, 37.50), (324.60, 60.40), (446.30, 83.30), (487.00, 91.00))
)


def irmaa_tier(magi: float, filing_status: str, scale: float = 1.0) -> int:
    """0 = no surcharge, 1-5 = surcharge tier."""
    tier = 0
    for i, floor in enumerate(IRMAA_FLOORS[filing_status]):
        # The top tier starts at the floor; the others start just above it.
        if magi > floor * scale or (i == len(IRMAA_FLOORS[filing_status]) - 1 and magi >= floor * scale):
            tier = i + 1
    return tier


def irmaa_surcharge(magi: float, filing_status: str, people_on_medicare: int, scale: float = 1.0) -> float:
    """Yearly surcharge for the household, in the same dollars as `scale` (nominal)."""
    tier = irmaa_tier(magi, filing_status, scale)
    if tier == 0 or people_on_medicare <= 0:
        return 0.0
    return IRMAA_ANNUAL_SURCHARGE[tier - 1] * scale * people_on_medicare

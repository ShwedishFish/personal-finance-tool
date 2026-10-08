"""ACA marketplace premium tax credit (IRC §36B) for coverage before Medicare.

Uses the original ACA rules that apply from 2026 after the enhanced (ARPA/IRA) credits expired:
no credit above 400% of the federal poverty line. Dollar amounts are 2026 values and scale with
inflation, as the poverty line does.
"""

# 2025 HHS poverty guidelines (48 contiguous states), which set 2026 coverage-year credits.
FPL_FIRST_PERSON = 15_650
FPL_EACH_ADDITIONAL = 5_500
MAX_FPL_RATIO = 4.0

# Rev. Proc. 2025-25: (income as a multiple of the poverty line up to, initial %, final %).
# Below 100% of poverty, people usually get Medicaid instead (or nothing in non-expansion
# states); the model treats them like the lowest band.
APPLICABLE_PERCENTAGES = (
    (1.33, 0.0210, 0.0210),
    (1.50, 0.0314, 0.0419),
    (2.00, 0.0419, 0.0660),
    (2.50, 0.0660, 0.0844),
    (3.00, 0.0844, 0.0996),
    (4.00, 0.0996, 0.0996),
)


def poverty_line(household_size: int, scale: float = 1.0) -> float:
    return (FPL_FIRST_PERSON + FPL_EACH_ADDITIONAL * max(household_size - 1, 0)) * scale


def applicable_percentage(fpl_ratio: float) -> float | None:
    """Share of income the household is expected to pay for the benchmark plan; None above 400%."""
    if fpl_ratio > MAX_FPL_RATIO:
        return None
    lower = 0.0
    for upper, start, end in APPLICABLE_PERCENTAGES:
        if fpl_ratio < upper or upper == MAX_FPL_RATIO:
            progress = max(fpl_ratio - lower, 0.0) / (upper - lower) if lower else 0.0
            return start + (end - start) * progress
        lower = upper
    return None


def premium_tax_credit(magi: float, household_size: int, benchmark_premium: float, scale: float = 1.0) -> float:
    """Yearly credit toward marketplace premiums: the benchmark silver premium minus the expected contribution."""
    if benchmark_premium <= 0 or household_size <= 0:
        return 0.0
    magi = max(magi, 0.0)
    pct = applicable_percentage(magi / poverty_line(household_size, scale))
    if pct is None:
        return 0.0
    return max(0.0, benchmark_premium - pct * magi)

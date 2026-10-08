"""State income taxes, 2026.

Rates, brackets, standard deductions, and personal exemptions are from the Tax Foundation,
"State Individual Income Tax Rates and Brackets, 2026" (as of January 1, 2026):
https://taxfoundation.org/data/all/state/state-income-tax-rates-2026/
Social Security treatment follows the eight states that still tax benefits in 2026 (Kiplinger, AARP,
Connecticut OLR report 2026-R-0106).

Simplifications: local income taxes, phaseouts of deductions and exemptions, Connecticut's benefit
recapture, and most partial pension exclusions are not modeled; brackets grow with inflation.
"""

from dataclasses import dataclass

INF = float("inf")


@dataclass(frozen=True)
class StateTax:
    name: str
    single: tuple[tuple[float, float], ...] = ()  # (taxable income over, marginal rate)
    married: tuple[tuple[float, float], ...] | None = None  # None = same as single
    deduction: tuple[float, float] = (0, 0)  # (single, married), standard deduction plus personal exemptions
    credit: tuple[float, float] = (0, 0)  # personal exemption credits
    taxes_social_security: bool = False
    ss_exempt_below_agi: tuple[float, float] | None = None  # full exemption under this federal AGI
    ss_exempt_at_65: bool = False
    retirement_exclusion: float = 0.0  # per person, on 401k/IRA withdrawals after 59½
    retirement_exclusion_65: float | None = None  # larger exclusion once 65
    capital_gains_exempt: bool = False
    capital_gains_only: bool = False

    def brackets(self, filing_status: str) -> tuple[tuple[float, float], ...]:
        return self.married if filing_status == "married_joint" and self.married is not None else self.single


def _flat(rate: float, over: float = 0) -> tuple[tuple[float, float], ...]:
    return ((over, rate),)


def _same(*brackets: tuple[float, float]) -> tuple[tuple[float, float], ...]:
    return brackets


STATES: dict[str, StateTax] = {
    "AL": StateTax("Alabama", ((0, 0.02), (500, 0.04), (3_000, 0.05)), ((0, 0.02), (1_000, 0.04), (6_000, 0.05)),
                   deduction=(3_000 + 1_500, 8_500 + 3_000)),
    "AK": StateTax("Alaska"),
    "AZ": StateTax("Arizona", _flat(0.025), deduction=(8_350, 16_700)),
    "AR": StateTax("Arkansas", _same((0, 0.02), (4_600, 0.039)), deduction=(2_470, 4_940), credit=(29, 58)),
    "CA": StateTax(
        "California",
        ((0, 0.01), (11_079, 0.02), (26_264, 0.04), (41_452, 0.06), (57_542, 0.08), (72_724, 0.093),
         (371_479, 0.103), (445_771, 0.113), (742_953, 0.123), (1_000_000, 0.133)),
        ((0, 0.01), (22_158, 0.02), (52_528, 0.04), (82_904, 0.06), (115_084, 0.08), (145_448, 0.093),
         (742_958, 0.103), (891_542, 0.113), (1_000_000, 0.123), (1_485_906, 0.133)),
        deduction=(5_540, 11_080), credit=(153, 306),
    ),
    "CO": StateTax("Colorado", _flat(0.044), deduction=(16_100, 32_200), taxes_social_security=True,
                   ss_exempt_at_65=True),
    "CT": StateTax(
        "Connecticut",
        ((0, 0.02), (10_000, 0.045), (50_000, 0.055), (100_000, 0.06), (200_000, 0.065), (250_000, 0.069),
         (500_000, 0.0699)),
        ((0, 0.02), (20_000, 0.045), (100_000, 0.055), (200_000, 0.06), (400_000, 0.065), (500_000, 0.069),
         (1_000_000, 0.0699)),
        deduction=(15_000, 24_000), taxes_social_security=True, ss_exempt_below_agi=(75_000, 100_000),
    ),
    "DE": StateTax("Delaware", _same((2_000, 0.022), (5_000, 0.039), (10_000, 0.048), (20_000, 0.052),
                                     (25_000, 0.0555), (60_000, 0.066)),
                   deduction=(3_250, 6_500), credit=(110, 220)),
    "FL": StateTax("Florida"),
    "GA": StateTax("Georgia", _flat(0.0519), deduction=(12_000, 24_000), retirement_exclusion=35_000,
                   retirement_exclusion_65=65_000),
    "HI": StateTax(
        "Hawaii",
        ((0, 0.014), (9_600, 0.032), (14_400, 0.055), (19_200, 0.064), (24_000, 0.068), (36_000, 0.072),
         (48_000, 0.076), (125_000, 0.079), (175_000, 0.0825), (225_000, 0.09), (275_000, 0.10), (325_000, 0.11)),
        ((0, 0.014), (19_200, 0.032), (28_800, 0.055), (38_400, 0.064), (48_000, 0.068), (72_000, 0.072),
         (96_000, 0.076), (250_000, 0.079), (350_000, 0.0825), (450_000, 0.09), (550_000, 0.10), (650_000, 0.11)),
        deduction=(4_400 + 1_144, 8_800 + 2_288),
    ),
    "ID": StateTax("Idaho", ((4_811, 0.053),), ((9_622, 0.053),), deduction=(16_100, 32_200)),
    "IL": StateTax("Illinois", _flat(0.0495), deduction=(2_925, 5_850), retirement_exclusion=INF),
    "IN": StateTax("Indiana", _flat(0.0295), deduction=(1_000, 2_000)),
    "IA": StateTax("Iowa", _flat(0.038), deduction=(16_100, 32_200), credit=(40, 80), retirement_exclusion=INF),
    "KS": StateTax("Kansas", ((0, 0.052), (23_000, 0.0558)), ((0, 0.052), (46_000, 0.0558)),
                   deduction=(3_605 + 9_160, 8_240 + 18_320)),
    "KY": StateTax("Kentucky", _flat(0.035), deduction=(3_360, 3_360)),
    "LA": StateTax("Louisiana", _flat(0.03), deduction=(12_875, 25_750)),
    "ME": StateTax("Maine", ((0, 0.058), (27_399, 0.0675), (64_849, 0.0715)),
                   ((0, 0.058), (54_849, 0.0675), (129_749, 0.0715)), deduction=(8_350 + 5_300, 16_700 + 10_600)),
    "MD": StateTax(
        "Maryland",
        ((0, 0.02), (1_000, 0.03), (2_000, 0.04), (3_000, 0.0475), (100_000, 0.05), (125_000, 0.0525),
         (150_000, 0.055), (250_000, 0.0575), (500_000, 0.0625), (1_000_000, 0.065)),
        ((0, 0.02), (1_000, 0.03), (2_000, 0.04), (3_000, 0.0475), (150_000, 0.05), (175_000, 0.0525),
         (225_000, 0.055), (300_000, 0.0575), (600_000, 0.0625), (1_200_000, 0.065)),
        deduction=(3_350 + 3_200, 6_700 + 6_400),
    ),
    "MA": StateTax("Massachusetts", _same((0, 0.05), (1_083_150, 0.09)), deduction=(4_400, 8_800)),
    "MI": StateTax("Michigan", _flat(0.0425), deduction=(5_900, 11_800)),
    "MN": StateTax("Minnesota", ((0, 0.0535), (33_310, 0.068), (109_430, 0.0785), (203_150, 0.0985)),
                   ((0, 0.0535), (48_700, 0.068), (193_480, 0.0785), (337_930, 0.0985)),
                   deduction=(15_300, 30_600), taxes_social_security=True),
    "MS": StateTax("Mississippi", _flat(0.04, 10_000), deduction=(2_300 + 6_000, 4_600 + 12_000),
                   retirement_exclusion=INF),
    "MO": StateTax("Missouri", _same((1_348, 0.02), (2_696, 0.025), (4_044, 0.03), (5_392, 0.035), (6_740, 0.04),
                                     (8_088, 0.045), (9_436, 0.047)),
                   deduction=(16_100, 32_200), capital_gains_exempt=True),
    "MT": StateTax("Montana", ((0, 0.047), (47_500, 0.0565)), ((0, 0.047), (95_000, 0.0565)),
                   deduction=(16_100, 32_200), taxes_social_security=True),
    "NE": StateTax("Nebraska", ((0, 0.0246), (4_130, 0.0351), (24_760, 0.0455)),
                   ((0, 0.0246), (8_250, 0.0351), (49_530, 0.0455)), deduction=(8_850, 17_700), credit=(176, 352)),
    "NV": StateTax("Nevada"),
    "NH": StateTax("New Hampshire"),
    "NJ": StateTax(
        "New Jersey",
        ((0, 0.014), (20_000, 0.0175), (35_000, 0.035), (40_000, 0.0553), (75_000, 0.0637), (500_000, 0.0897),
         (1_000_000, 0.1075)),
        ((0, 0.014), (20_000, 0.0175), (50_000, 0.0245), (70_000, 0.035), (80_000, 0.0553), (150_000, 0.0637),
         (500_000, 0.0897), (1_000_000, 0.1075)),
        deduction=(1_000, 2_000),
    ),
    "NM": StateTax(
        "New Mexico",
        ((0, 0.015), (5_500, 0.032), (16_500, 0.043), (33_500, 0.047), (66_500, 0.049), (210_000, 0.059)),
        ((0, 0.015), (8_000, 0.032), (25_000, 0.043), (50_000, 0.047), (100_000, 0.049), (315_000, 0.059)),
        deduction=(16_100, 32_200), taxes_social_security=True, ss_exempt_below_agi=(100_000, 150_000),
    ),
    "NY": StateTax(
        "New York",
        ((0, 0.039), (8_500, 0.044), (11_700, 0.0515), (13_900, 0.054), (80_650, 0.059), (215_400, 0.0685),
         (1_077_550, 0.0965), (5_000_000, 0.103), (25_000_000, 0.109)),
        ((0, 0.039), (17_150, 0.044), (23_600, 0.0515), (27_900, 0.054), (161_550, 0.059), (323_200, 0.0685),
         (2_155_350, 0.0965), (5_000_000, 0.103), (25_000_000, 0.109)),
        deduction=(8_000, 16_050), retirement_exclusion=20_000,
    ),
    "NC": StateTax("North Carolina", _flat(0.0399), deduction=(12_750, 25_500)),
    "ND": StateTax("North Dakota", ((48_475, 0.0195), (244_825, 0.025)), ((80_975, 0.0195), (298_075, 0.025)),
                   deduction=(16_100, 32_200)),
    "OH": StateTax("Ohio", _flat(0.0275, 26_050), deduction=(2_400, 4_800)),
    "OK": StateTax("Oklahoma", ((3_750, 0.025), (4_900, 0.035), (7_200, 0.045)),
                   ((7_500, 0.025), (9_800, 0.035), (14_400, 0.045)), deduction=(6_350 + 1_000, 12_700 + 2_000)),
    "OR": StateTax("Oregon", ((0, 0.0475), (4_550, 0.0675), (11_400, 0.0875), (125_000, 0.099)),
                   ((0, 0.0475), (9_100, 0.0675), (22_800, 0.0875), (250_000, 0.099)),
                   deduction=(2_910, 5_820), credit=(256, 512)),
    "PA": StateTax("Pennsylvania", _flat(0.0307), retirement_exclusion=INF),
    "RI": StateTax("Rhode Island", _same((0, 0.0375), (82_050, 0.0475), (186_450, 0.0599)),
                   deduction=(11_200 + 5_250, 22_400 + 10_500), taxes_social_security=True),
    "SC": StateTax("South Carolina", _same((3_640, 0.03), (18_230, 0.06)), deduction=(8_350, 16_700)),
    "SD": StateTax("South Dakota"),
    "TN": StateTax("Tennessee"),
    "TX": StateTax("Texas"),
    "UT": StateTax("Utah", _flat(0.045), credit=(966, 1_932), taxes_social_security=True),
    "VT": StateTax(
        "Vermont",
        ((0, 0.0335), (49_400, 0.066), (119_700, 0.076), (249_700, 0.0875)),
        ((0, 0.0335), (82_500, 0.066), (199_450, 0.076), (304_000, 0.0875)),
        deduction=(7_650 + 5_300, 15_300 + 10_600), taxes_social_security=True, ss_exempt_below_agi=(55_000, 70_000),
    ),
    "VA": StateTax("Virginia", _same((0, 0.02), (3_000, 0.03), (5_000, 0.05), (17_000, 0.0575)),
                   deduction=(8_750 + 930, 17_500 + 1_860)),
    "WA": StateTax("Washington", _same((0, 0.07), (1_000_000, 0.09)), deduction=(278_000, 278_000),
                   capital_gains_only=True),
    "WV": StateTax("West Virginia", _same((0, 0.0222), (10_000, 0.0296), (25_000, 0.0333), (40_000, 0.0444),
                                          (60_000, 0.0482)),
                   deduction=(2_000, 4_000)),
    "WI": StateTax("Wisconsin", ((0, 0.035), (15_110, 0.044), (51_950, 0.053), (332_720, 0.0765)),
                   ((0, 0.035), (20_150, 0.044), (69_260, 0.053), (443_630, 0.0765)),
                   deduction=(13_960 + 700, 25_840 + 1_400)),
    "WY": StateTax("Wyoming"),
    "DC": StateTax("District of Columbia", _same((0, 0.04), (10_000, 0.06), (40_000, 0.065), (60_000, 0.085),
                                                 (250_000, 0.0925), (500_000, 0.0975), (1_000_000, 0.1075)),
                   deduction=(16_100, 32_200)),
}


def bracket_tax(taxable: float, brackets: tuple[tuple[float, float], ...], scale: float = 1.0) -> float:
    tax = 0.0
    for i, (over, rate) in enumerate(brackets):
        lo = over * scale
        hi = brackets[i + 1][0] * scale if i + 1 < len(brackets) else INF
        if taxable <= lo:
            break
        tax += (min(taxable, hi) - lo) * rate
    return tax


def state_income_tax(
    code: str,
    filing_status: str,
    *,
    other_income: float,
    social_security_taxable: float,
    federal_agi: float,
    capital_gains: float,
    retirement_withdrawals: float,
    people_65_plus: int,
    scale: float = 1.0,
) -> float:
    """State tax for one year. `other_income` is ordinary income other than Social Security; it
    includes `retirement_withdrawals` (401k/IRA withdrawals after 59½, which some states exclude).
    """
    state = STATES[code]
    married = filing_status == "married_joint"
    i = 1 if married else 0
    if state.capital_gains_only:
        return bracket_tax(max(0.0, capital_gains - state.deduction[i] * scale), state.brackets(filing_status), scale)
    if not state.single:
        return 0.0

    income = other_income
    if state.retirement_exclusion:
        people = 2 if married else 1
        older = state.retirement_exclusion_65 or state.retirement_exclusion
        caps = [older if p < people_65_plus else state.retirement_exclusion for p in range(people)]
        income -= min(retirement_withdrawals, sum(caps) * scale)
    if state.taxes_social_security:
        exempt = (state.ss_exempt_at_65 and people_65_plus > 0) or (
            state.ss_exempt_below_agi is not None and federal_agi < state.ss_exempt_below_agi[i] * scale
        )
        if not exempt:
            income += social_security_taxable
    if not state.capital_gains_exempt:
        income += capital_gains

    taxable = max(0.0, income - state.deduction[i] * scale)
    return max(0.0, bracket_tax(taxable, state.brackets(filing_status), scale) - state.credit[i] * scale)

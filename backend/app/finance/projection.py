"""Lifetime cash-flow projection and Monte Carlo simulation.

Inputs are expressed in today's dollars; the simulation runs in nominal dollars
(inflating flows each year) and reports both nominal and real (today's dollar) results.
Each simulated year applies cash flows first, then investment growth.
"""

import random
from dataclasses import asdict, dataclass, field, replace

from .aca import premium_tax_credit
from .historical_data import ANNUAL_RETURNS
from .medicare import IRMAA_LOOKBACK_YEARS, MEDICARE_AGE, irmaa_surcharge
from .tax import (
    EARLY_WITHDRAWAL_AGE,
    TaxBreakdown,
    TaxProfile,
    YearIncome,
    aca_income,
    adjusted_gross_income,
    bracket_ceiling,
    income_tax,
    ordinary_taxable_income,
    required_minimum_distribution,
    rmd_start_age,
)

HEIR_TAX_RATE = 0.22  # assumed tax on inherited 401k/IRA money, for after-tax comparisons
EMBEDDED_GAINS_RATE = 0.15  # assumed tax on unrealized gains, for after-tax comparisons

TAX_TYPES = ("wages", "ordinary", "social_security", "tax_free")
SURVIVOR_UNSCALED_CATEGORIES = ("kids", "education")
GUARDRAIL_FIXED_CATEGORIES = ("housing", "utilities", "healthcare", "insurance", "kids", "education")
GUARDRAIL_NO_CUT_YEARS = 15  # Guyton-Klinger: no cuts in the plan's final 15 years


@dataclass
class FlowInput:
    name: str
    kind: str  # "income" | "expense" | "goal"
    amount: float  # annual, today's dollars
    start_age: int
    end_age: int  # inclusive
    real_growth: float = 0.0
    tax_type: str = "wages"  # income only; see TAX_TYPES
    category: str = "general"  # expenses only
    every_n_years: int = 1  # 1 = every year; e.g. 8 = a car every 8 years starting at start_age
    owner: str = ""  # "self" | "spouse": the flow stops when that person dies; "" = household
    spousal: bool = False  # Social Security spousal top-up, paid only while both spouses are alive

    def active(self, age: int) -> bool:
        if not (self.start_age <= age <= self.end_age):
            return False
        return (age - self.start_age) % max(self.every_n_years, 1) == 0


@dataclass
class DebtInput:
    name: str
    balance: float
    apr: float
    monthly_payment: float


@dataclass
class ProjectionInput:
    current_age: int
    retirement_age: int
    life_expectancy: int
    start_year: int
    inflation: float = 0.025
    expected_return: float = 0.07
    retirement_return: float = 0.05
    return_volatility: float = 0.15
    # "simple": the two returns above. "allocation": a stock/bond mix that glides from
    # stock_allocation_now today to stock_allocation_retired when the first of you retires.
    return_model: str = "simple"
    stock_return: float = 0.085
    bond_return: float = 0.045
    stock_volatility: float = 0.17
    bond_volatility: float = 0.06
    stock_bond_correlation: float = 0.1
    stock_allocation_now: float = 0.9
    stock_allocation_retired: float = 0.6
    cash_return: float = 0.03
    tax_mode: str = "progressive"
    filing_status: str = "single"
    effective_tax_rate: float = 0.15  # used when tax_mode == "flat"
    state_tax_rate: float = 0.0
    state: str = ""  # two-letter code; when set, that state's rules replace state_tax_rate
    withdrawal_rate: float = 0.04
    # Guyton-Klinger guardrails on flexible spending once everyone is retired: if the withdrawal
    # rate drifts more than `guardrail_band` above (below) its starting level, cut (raise)
    # flexible spending by `guardrail_adjustment`, never below `guardrail_floor` of the plan.
    guardrails: bool = False
    guardrail_band: float = 0.2
    guardrail_adjustment: float = 0.1
    guardrail_floor: float = 0.7
    spouse_current_age: int | None = None
    spouse_life_expectancy: int | None = None  # in the spouse's age; None = outlives the plan
    spouse_retirement_age: int | None = None  # in the spouse's age; None = the same year as you
    survivor_spending: float = 1.0  # share of household spending that continues after the first death
    cash: float = 0.0
    taxable: float = 0.0
    taxable_basis: float | None = None  # None = no unrealized gains
    tax_deferred: float = 0.0
    tax_free: float = 0.0
    other_assets: float = 0.0
    roth_conversion_rate: float | None = None  # fill this federal bracket with conversions each year
    roth_start_age: int | None = None  # default: retirement age
    roth_end_age: int | None = None  # default: the year before RMDs start
    contrib_taxable: float = 0.0  # yearly contributions while you work
    contrib_tax_deferred: float = 0.0
    contrib_tax_free: float = 0.0
    spouse_contrib_taxable: float = 0.0  # yearly contributions while your spouse works
    spouse_contrib_tax_deferred: float = 0.0
    spouse_contrib_tax_free: float = 0.0
    debts: list[DebtInput] = field(default_factory=list)
    flows: list[FlowInput] = field(default_factory=list)
    # Benchmark silver premiums for marketplace coverage before Medicare; each year the ACA credit
    # is computed from the active ones and household income.
    aca_benchmarks: list[FlowInput] = field(default_factory=list)

    @property
    def birth_year(self) -> int:
        return self.start_year - self.current_age

    @property
    def has_spouse(self) -> bool:
        return self.spouse_current_age is not None

    @property
    def spouse_age_offset(self) -> int:
        """Your age minus your spouse's age."""
        return self.current_age - self.spouse_current_age if self.has_spouse else 0

    @property
    def spouse_retirement_in_your_age(self) -> int:
        if not self.has_spouse or self.spouse_retirement_age is None:
            return self.retirement_age
        return self.spouse_retirement_age + self.spouse_age_offset

    @property
    def first_retirement_age(self) -> int:
        """In your age: when the first of you retires (the portfolio shifts to the retirement return)."""
        return min(self.retirement_age, self.spouse_retirement_in_your_age)

    @property
    def last_retirement_age(self) -> int:
        """In your age: when the household is fully retired."""
        return max(self.retirement_age, self.spouse_retirement_in_your_age)

    @property
    def end_age(self) -> int:
        """Last year of the plan, in your age: the later of the two life expectancies."""
        end = self.life_expectancy
        if self.has_spouse and self.spouse_life_expectancy is not None:
            end = max(end, self.spouse_life_expectancy + self.spouse_age_offset)
        return end

    @property
    def tax_profile(self) -> TaxProfile:
        return TaxProfile(
            mode=self.tax_mode,
            filing_status=self.filing_status,
            flat_rate=min(max(self.effective_tax_rate, 0.0), 0.95),
            state_rate=self.state_tax_rate,
            state=self.state,
        )


@dataclass
class YearRow:
    year: int
    age: int
    spouse_age: int | None
    self_alive: bool
    spouse_alive: bool | None
    filing_status: str
    retired: bool
    stock_allocation: float | None
    investment_return: float
    spending_adjustment: float  # guardrail multiplier on flexible spending; 1.0 = as planned
    income: float
    taxes: float
    tax_federal: float
    tax_state: float
    tax_fica: float
    tax_penalty: float
    expenses: float
    goals: float
    debt_payments: float
    contributions: float
    irmaa: float
    aca_credit: float  # ACA premium tax credit, already netted out of expenses
    rmd: float
    roth_conversion: float
    realized_gains: float
    net_cash_flow: float
    withdrawals: float
    shortfall: float
    cash: float
    taxable: float
    taxable_basis: float
    tax_deferred: float
    tax_free: float
    other_assets: float
    liabilities: float
    investable: float
    net_worth: float
    investable_real: float
    net_worth_real: float
    goal_names: list[str] = field(default_factory=list)
    expenses_by_category_real: dict[str, float] = field(default_factory=dict)


def _years(inp: ProjectionInput) -> range:
    return range(inp.current_age, inp.end_age + 1)


def _glide(inp: ProjectionInput, age: int) -> float:
    start, end = inp.current_age, inp.first_retirement_age
    if age >= end or end <= start:
        return inp.stock_allocation_retired
    progress = (age - start) / (end - start)
    return inp.stock_allocation_now + (inp.stock_allocation_retired - inp.stock_allocation_now) * progress


def stock_allocation(inp: ProjectionInput, age: int) -> float | None:
    """Share of investments in stocks at `age`, or None for the simple return model."""
    return _glide(inp, age) if inp.return_model == "allocation" else None


def _mean_return(inp: ProjectionInput, age: int) -> float:
    w = stock_allocation(inp, age)
    if w is None:
        return inp.retirement_return if age >= inp.first_retirement_age else inp.expected_return
    return w * inp.stock_return + (1 - w) * inp.bond_return


def portfolio_returns(inp: ProjectionInput, stocks: list[float], bonds: list[float]) -> list[float]:
    """Yearly portfolio returns for given stock and bond return paths, using the glide path."""
    out = []
    for age, s, b in zip(_years(inp), stocks, bonds, strict=False):
        w = _glide(inp, age)
        out.append(w * s + (1 - w) * b)
    return out


def random_returns(inp: ProjectionInput, rng: random.Random) -> list[float]:
    """One Monte Carlo path of yearly portfolio returns."""
    ages = list(_years(inp))
    if inp.return_model != "allocation":
        return [rng.gauss(_mean_return(inp, age), inp.return_volatility) for age in ages]
    rho = max(-1.0, min(1.0, inp.stock_bond_correlation))
    stocks, bonds = [], []
    for _ in ages:
        z1, z2 = rng.gauss(0, 1), rng.gauss(0, 1)
        stocks.append(inp.stock_return + inp.stock_volatility * z1)
        bonds.append(inp.bond_return + inp.bond_volatility * (rho * z1 + (1 - rho * rho) ** 0.5 * z2))
    return portfolio_returns(inp, stocks, bonds)


def _gross_up(need: float, cap: float, tax_at) -> float:
    """Smallest withdrawal g (<= cap) with g - (tax_at(g) - tax_at(0)) >= need.

    Tax is piecewise linear in g, so secant steps land on the answer in a few evaluations.
    """
    base = tax_at(0.0)

    def short(g: float) -> float:
        return need - (g - (tax_at(g) - base))

    g0, s0 = need, short(need)
    if s0 <= 0.001:
        return min(need, cap)
    g1 = need + s0
    for _ in range(30):
        s1 = short(g1)
        if abs(s1) < 0.001:
            break
        slope = (s0 - s1) / (g1 - g0) if g1 != g0 else 0.0
        g0, s0 = g1, s1
        # A flat or backwards slope means a kink was crossed; fall back to a fixed-point step.
        g1 = g1 + s1 / slope if slope > 1e-6 else g1 + s1
        if g1 >= cap and short(cap) >= 0:
            return cap
    return min(g1, cap)


def after_tax_value(row: YearRow) -> float:
    """Investable assets net of the taxes still embedded in them (nominal)."""
    gains = max(0.0, row.taxable - row.taxable_basis)
    return (
        row.cash + row.taxable - gains * EMBEDDED_GAINS_RATE + row.tax_free + row.tax_deferred * (1 - HEIR_TAX_RATE)
    )


def simulate(inp: ProjectionInput, returns: list[float] | None = None) -> list[YearRow]:
    cash, taxable, deferred, free = inp.cash, inp.taxable, inp.tax_deferred, inp.tax_free
    basis = inp.taxable if inp.taxable_basis is None else inp.taxable_basis
    other = inp.other_assets
    debts = [[d.balance, d.apr, d.monthly_payment] for d in inp.debts]
    joint_profile = inp.tax_profile
    single_profile = replace(joint_profile, filing_status="single")
    birth_year = inp.birth_year
    spouse_birth_year = inp.start_year - inp.spouse_current_age if inp.has_spouse else None
    roth_start = inp.roth_start_age if inp.roth_start_age is not None else inp.last_retirement_age
    spouse_retires = inp.spouse_retirement_in_your_age
    roth_end = inp.roth_end_age if inp.roth_end_age is not None else rmd_start_age(birth_year) - 1
    convert = inp.roth_conversion_rate is not None and inp.tax_mode == "progressive"
    magi_history: list[float] = []
    rows: list[YearRow] = []
    flex = 1.0
    initial_rate: float | None = None

    for t, age in enumerate(_years(inp)):
        investable_start = cash + taxable + deferred + free
        infl = (1 + inp.inflation) ** t
        retired = age >= inp.last_retirement_age
        r = returns[t] if returns is not None else _mean_return(inp, age)
        r = max(r, -0.95)

        spouse_age = inp.spouse_current_age + t if inp.has_spouse else None
        self_alive = age <= inp.life_expectancy
        spouse_alive = inp.has_spouse and (
            inp.spouse_life_expectancy is None or spouse_age <= inp.spouse_life_expectancy
        )
        widowed = inp.has_spouse and not (self_alive and spouse_alive)
        alive = {"": True, "self": self_alive, "spouse": spouse_alive}
        profile = single_profile if widowed else joint_profile
        filing = profile.filing_status

        income_by_type = dict.fromkeys(TAX_TYPES, 0.0)
        own_benefit = {"self": 0.0, "spouse": 0.0}
        expenses = goals = 0.0
        goal_names: list[str] = []
        by_category: dict[str, float] = {}
        flexible: dict[str, float] = {}
        for f in inp.flows:
            if not f.active(age):
                continue
            nominal = f.amount * infl * (1 + f.real_growth) ** t
            if f.kind == "income" and f.tax_type == "social_security" and f.owner in own_benefit:
                if not f.spousal:
                    own_benefit[f.owner] += nominal
                elif not widowed:
                    income_by_type["social_security"] += nominal
                continue
            if not alive.get(f.owner, True):
                continue
            if f.kind == "income":
                income_by_type[f.tax_type if f.tax_type in income_by_type else "ordinary"] += nominal
            elif f.kind == "goal":
                goals += nominal
                goal_names.append(f.name)
            else:
                if widowed and not f.owner and f.category not in SURVIVOR_UNSCALED_CATEGORIES:
                    nominal *= inp.survivor_spending
                bucket = by_category if f.category in GUARDRAIL_FIXED_CATEGORIES else flexible
                bucket[f.category] = bucket.get(f.category, 0.0) + nominal
        # A surviving spouse keeps the larger of the two retirement benefits.
        if widowed:
            income_by_type["social_security"] += max(own_benefit.values())
        else:
            income_by_type["social_security"] += sum(own_benefit.values())

        if inp.guardrails and retired and investable_start > 0:
            fixed, flex_total = sum(by_category.values()), sum(flexible.values())
            rate = max(fixed + flex_total * flex - sum(income_by_type.values()), 0.0) / investable_start
            if initial_rate is None:
                initial_rate = rate
            elif rate > initial_rate * (1 + inp.guardrail_band) and inp.end_age - age >= GUARDRAIL_NO_CUT_YEARS:
                flex = max(flex * (1 - inp.guardrail_adjustment), inp.guardrail_floor)
            elif rate < initial_rate * (1 - inp.guardrail_band):
                flex *= 1 + inp.guardrail_adjustment
        for category, amount in flexible.items():
            by_category[category] = by_category.get(category, 0.0) + amount * flex
        expenses = sum(by_category.values())

        you_work = self_alive and age < inp.retirement_age
        spouse_works = bool(spouse_alive) and age < spouse_retires
        c_deferred = (inp.contrib_tax_deferred * you_work + inp.spouse_contrib_tax_deferred * spouse_works) * infl
        c_free = (inp.contrib_tax_free * you_work + inp.spouse_contrib_tax_free * spouse_works) * infl
        c_taxable = (inp.contrib_taxable * you_work + inp.spouse_contrib_taxable * spouse_works) * infl

        debt_payments = 0.0
        for d in debts:
            if d[0] <= 0:
                continue
            owed = d[0] * (1 + d[1])
            payment = min(d[2] * 12, owed)
            d[0] = owed - payment
            debt_payments += payment

        if self_alive or not inp.has_spouse:
            rmd = required_minimum_distribution(deferred, age, birth_year)
        else:
            rmd = required_minimum_distribution(deferred, spouse_age, spouse_birth_year)
        deferred -= rmd
        self_65 = self_alive and age >= MEDICARE_AGE
        spouse_65 = bool(spouse_alive) and spouse_age >= MEDICARE_AGE
        people_65 = int(self_65) + int(spouse_65 and filing == "married_joint")
        early = (age if self_alive or not inp.has_spouse else spouse_age) < EARLY_WITHDRAWAL_AGE
        conversion = 0.0

        def year_income(extra_deferred: float = 0.0, gains: float = 0.0) -> YearIncome:
            return YearIncome(
                wages=income_by_type["wages"],
                ordinary=income_by_type["ordinary"],
                social_security=income_by_type["social_security"],
                pre_tax_contributions=c_deferred,
                deferred_withdrawals=rmd + conversion + extra_deferred,
                early_withdrawals=extra_deferred if early else 0.0,
                capital_gains=gains,
                scale=infl,
                people_65_plus=people_65,
            )

        def tax_for(extra_deferred: float = 0.0, gains: float = 0.0) -> TaxBreakdown:
            return income_tax(profile, year_income(extra_deferred, gains))

        if convert and roth_start <= age <= roth_end and deferred > 0:
            ceiling = bracket_ceiling(inp.roth_conversion_rate, filing, infl)
            for _ in range(4):  # taxable Social Security rises with conversions, so iterate
                conversion = max(0.0, conversion + ceiling - ordinary_taxable_income(profile, year_income()))
            conversion = min(conversion, deferred)
            deferred -= conversion
            free += conversion

        irmaa = 0.0
        on_medicare = int(self_65) + int(spouse_65)
        if on_medicare:
            lookback = t - IRMAA_LOOKBACK_YEARS
            # Before there is history, estimate from this year's income before withdrawals.
            magi = magi_history[lookback] if lookback >= 0 else adjusted_gross_income(profile, year_income())
            irmaa = irmaa_surcharge(magi, filing, on_medicare, infl)
            expenses += irmaa
            by_category["healthcare"] = by_category.get("healthcare", 0.0) + irmaa

        tax = tax_for()
        income = sum(income_by_type.values())
        net = income + rmd - tax.total - expenses - goals - debt_payments - c_deferred - c_free - c_taxable

        deferred += c_deferred
        free += c_free
        taxable += c_taxable
        basis += c_taxable

        withdrawals = shortfall = realized = drawn_deferred = 0.0
        if net >= 0:
            taxable += net
            basis += net
        else:
            need = -net
            take = min(cash, need)
            cash -= take
            need -= take
            withdrawals += take

            if need > 0 and taxable > 0:
                gain_share = max(0.0, 1 - basis / taxable)
                before = tax.total
                gross = _gross_up(need, taxable, lambda g: tax_for(gains=g * gain_share).total)
                realized = gross * gain_share
                tax = tax_for(gains=realized)
                basis -= gross - realized
                taxable -= gross
                need -= gross - (tax.total - before)
                withdrawals += gross

            if need > 0 and deferred > 0:
                before = tax.total
                gross = _gross_up(need, deferred, lambda g: tax_for(g, realized).total)
                tax = tax_for(gross, realized)
                deferred -= gross
                drawn_deferred = gross
                need -= gross - (tax.total - before)
                withdrawals += gross

            take = min(free, max(need, 0.0))
            free -= take
            need -= take
            withdrawals += take
            if need > 1.0:
                shortfall = need
        magi_history.append(adjusted_gross_income(profile, year_income(drawn_deferred, realized)))

        # The ACA credit is reconciled on the tax return, so it comes back after the year's withdrawals.
        aca_credit = 0.0
        benchmark = sum(
            f.amount * infl * (1 + f.real_growth) ** t
            for f in inp.aca_benchmarks
            if f.active(age) and alive.get(f.owner, True)
        )
        if benchmark > 0:
            household = int(self_alive) + int(bool(spouse_alive)) if inp.has_spouse else 1
            magi = aca_income(year_income(drawn_deferred, realized))
            aca_credit = premium_tax_credit(magi, household, benchmark, infl)
            taxable += aca_credit
            basis += aca_credit
            expenses -= aca_credit
            by_category["healthcare"] = by_category.get("healthcare", 0.0) - aca_credit

        cash *= 1 + inp.cash_return
        taxable *= 1 + r
        deferred *= 1 + r
        free *= 1 + r
        other *= 1 + inp.inflation

        liabilities = sum(d[0] for d in debts)
        investable = cash + taxable + deferred + free
        net_worth = investable + other - liabilities
        deflator = (1 + inp.inflation) ** (t + 1)
        rows.append(
            YearRow(
                year=inp.start_year + t,
                age=age,
                spouse_age=spouse_age,
                self_alive=self_alive,
                spouse_alive=spouse_alive if inp.has_spouse else None,
                filing_status=filing,
                retired=retired,
                stock_allocation=stock_allocation(inp, age),
                investment_return=r,
                income=income,
                taxes=tax.total,
                tax_federal=tax.federal,
                tax_state=tax.state,
                tax_fica=tax.fica,
                tax_penalty=tax.penalty,
                expenses=expenses,
                spending_adjustment=flex,
                goals=goals,
                debt_payments=debt_payments,
                contributions=c_deferred + c_free + c_taxable,
                irmaa=irmaa,
                aca_credit=aca_credit,
                rmd=rmd,
                roth_conversion=conversion,
                realized_gains=realized,
                net_cash_flow=net,
                withdrawals=withdrawals,
                shortfall=shortfall,
                cash=cash,
                taxable=taxable,
                taxable_basis=basis,
                tax_deferred=deferred,
                tax_free=free,
                other_assets=other,
                liabilities=liabilities,
                investable=investable,
                net_worth=net_worth,
                investable_real=investable / deflator,
                net_worth_real=net_worth / deflator,
                goal_names=goal_names,
                expenses_by_category_real={k: v / infl for k, v in by_category.items()},
            )
        )
    return rows


def fi_number(inp: ProjectionInput) -> float:
    """Investable assets (today's dollars) needed to cover first-year retirement spending at the withdrawal rate."""
    if inp.withdrawal_rate <= 0:
        return 0.0
    retire = inp.last_retirement_age
    t = max(retire - inp.current_age, 0)
    spending = sum(
        f.amount * (1 + f.real_growth) ** t / max(f.every_n_years, 1)
        for f in inp.flows
        if f.kind == "expense" and f.start_age <= retire <= f.end_age
    )
    return spending / inp.withdrawal_rate


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def summarize_paths(inp: ProjectionInput, paths, outcomes: list | None = None) -> dict:
    """Run the plan once per return path; success rate, failure ages, and percentile bands.

    If `outcomes` is given, (depletion age or None, ending investable in today's dollars) is appended per path.
    """
    ages = list(_years(inp))
    by_year: list[list[float]] = [[] for _ in ages]
    successes = runs = 0
    depletion_ages: list[int] = []
    lowest_spending: list[float] = []
    for returns in paths:
        runs += 1
        rows = simulate(inp, returns)
        lowest_spending.append(min((row.spending_adjustment for row in rows), default=1.0))
        failed_at = next((row.age for row in rows if row.shortfall > 0), None)
        if failed_at is None:
            successes += 1
        else:
            depletion_ages.append(failed_at)
        for i, row in enumerate(rows):
            by_year[i].append(row.investable_real)
        if outcomes is not None:
            outcomes.append((failed_at, rows[-1].investable_real if rows else 0.0))

    bands = []
    for age, values in zip(ages, by_year, strict=True):
        values.sort()
        bands.append(
            {
                "age": age,
                "year": inp.start_year + age - inp.current_age,
                **{f"p{int(p * 100)}": _percentile(values, p) for p in (0.1, 0.25, 0.5, 0.75, 0.9)},
            }
        )
    depletion_ages.sort()
    lowest_spending.sort()
    return {
        # Lowest guardrail multiplier on flexible spending reached in a path (1.0 without guardrails).
        "lowest_spending_p10": _percentile(lowest_spending, 0.1) if lowest_spending else 1.0,
        "lowest_spending_p50": _percentile(lowest_spending, 0.5) if lowest_spending else 1.0,
        "simulations": runs,
        "success_rate": successes / runs if runs else 0.0,
        "median_depletion_age": _percentile(depletion_ages, 0.5) if depletion_ages else None,
        "bands": bands,
    }


def monte_carlo(inp: ProjectionInput, simulations: int = 1000, seed: int = 42) -> dict:
    rng = random.Random(seed)
    return summarize_paths(inp, (random_returns(inp, rng) for _ in range(simulations)))


def historical_paths(inp: ProjectionInput, data=ANNUAL_RETURNS) -> list[tuple[int, list[float]]]:
    """(start year, portfolio returns) for every complete historical window as long as the plan.

    Each year's real stock and bond returns are re-inflated at the plan's inflation rate, so the plan
    experiences history's real returns while its spending keeps growing at the assumed inflation.
    """
    n = len(_years(inp))
    paths = []
    for start in range(len(data) - n + 1):
        window = data[start : start + n]
        stocks = [(1 + s) / (1 + cpi) * (1 + inp.inflation) - 1 for _, s, _, cpi in window]
        bonds = [(1 + b) / (1 + cpi) * (1 + inp.inflation) - 1 for _, _, b, cpi in window]
        paths.append((window[0][0], portfolio_returns(inp, stocks, bonds)))
    return paths


def backtest(inp: ProjectionInput, data=ANNUAL_RETURNS) -> dict | None:
    """Replay the plan through every historical sequence of returns; None if history is too short."""
    paths = historical_paths(inp, data)
    if not paths:
        return None
    outcomes: list = []
    summary = summarize_paths(inp, (returns for _, returns in paths), outcomes)
    starts = [
        {"start_year": year, "depletion_age": failed_at, "ending_real": ending}
        for (year, _), (failed_at, ending) in zip(paths, outcomes, strict=True)
    ]
    worst = min(starts, key=lambda s: (s["depletion_age"] is None, s["depletion_age"] or 0, s["ending_real"]))
    return {
        **summary,
        "first_year": data[0][0],
        "last_year": data[-1][0],
        "starts": starts,
        "worst_start_year": worst["start_year"],
    }


def lifetime_taxes_real(inp: ProjectionInput, rows: list[YearRow]) -> float:
    return sum(row.taxes / (1 + inp.inflation) ** (row.age - inp.current_age) for row in rows)


def after_tax_ending_real(inp: ProjectionInput, rows: list[YearRow]) -> float:
    if not rows:
        return 0.0
    return after_tax_value(rows[-1]) / (1 + inp.inflation) ** len(rows)


def project(inp: ProjectionInput, simulations: int = 1000, seed: int = 42) -> dict:
    rows = simulate(inp)
    target = fi_number(inp)
    fi_age = next((row.age for row in rows if target > 0 and row.investable_real >= target), None)
    depleted = next((row.age for row in rows if row.shortfall > 0), None)
    return {
        "fi_number": target,
        "fi_age": fi_age,
        "depletion_age": depleted,
        "lifetime_taxes_real": lifetime_taxes_real(inp, rows),
        "after_tax_ending_real": after_tax_ending_real(inp, rows),
        "years": [asdict(row) for row in rows],
        "monte_carlo": monte_carlo(inp, simulations, seed) if simulations > 0 else None,
        "backtest": backtest(inp) if simulations > 0 else None,
    }

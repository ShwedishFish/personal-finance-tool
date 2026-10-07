"""Lifetime cash-flow projection and Monte Carlo simulation.

Inputs are expressed in today's dollars; the simulation runs in nominal dollars
(inflating flows each year) and reports both nominal and real (today's dollar) results.
Each simulated year applies cash flows first, then investment growth.
"""

import random
from dataclasses import asdict, dataclass, field

from .tax import (
    EARLY_WITHDRAWAL_AGE,
    TaxBreakdown,
    TaxProfile,
    YearIncome,
    bracket_ceiling,
    income_tax,
    ordinary_taxable_income,
    required_minimum_distribution,
    rmd_start_age,
)

HEIR_TAX_RATE = 0.22  # assumed tax on inherited 401k/IRA money, for after-tax comparisons
EMBEDDED_GAINS_RATE = 0.15  # assumed tax on unrealized gains, for after-tax comparisons

TAX_TYPES = ("wages", "ordinary", "social_security", "tax_free")


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
    cash_return: float = 0.03
    tax_mode: str = "progressive"
    filing_status: str = "single"
    effective_tax_rate: float = 0.15  # used when tax_mode == "flat"
    state_tax_rate: float = 0.0
    withdrawal_rate: float = 0.04
    spouse_current_age: int | None = None
    cash: float = 0.0
    taxable: float = 0.0
    taxable_basis: float | None = None  # None = no unrealized gains
    tax_deferred: float = 0.0
    tax_free: float = 0.0
    other_assets: float = 0.0
    roth_conversion_rate: float | None = None  # fill this federal bracket with conversions each year
    roth_start_age: int | None = None  # default: retirement age
    roth_end_age: int | None = None  # default: the year before RMDs start
    contrib_taxable: float = 0.0
    contrib_tax_deferred: float = 0.0
    contrib_tax_free: float = 0.0
    debts: list[DebtInput] = field(default_factory=list)
    flows: list[FlowInput] = field(default_factory=list)

    @property
    def birth_year(self) -> int:
        return self.start_year - self.current_age

    @property
    def tax_profile(self) -> TaxProfile:
        return TaxProfile(
            mode=self.tax_mode,
            filing_status=self.filing_status,
            flat_rate=min(max(self.effective_tax_rate, 0.0), 0.95),
            state_rate=self.state_tax_rate,
        )


@dataclass
class YearRow:
    year: int
    age: int
    retired: bool
    investment_return: float
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
    return range(inp.current_age, inp.life_expectancy + 1)


def _mean_return(inp: ProjectionInput, age: int) -> float:
    return inp.retirement_return if age >= inp.retirement_age else inp.expected_return


def _gross_up(need: float, cap: float, tax_at) -> float:
    """Smallest withdrawal g (<= cap) with g - (tax_at(g) - tax_at(0)) >= need, by fixed-point iteration."""
    base = tax_at(0.0)
    gross = need
    for _ in range(40):
        nxt = need + tax_at(min(gross, cap)) - base
        if abs(nxt - gross) < 0.001:
            gross = nxt
            break
        gross = nxt
    return min(gross, cap)


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
    profile = inp.tax_profile
    birth_year = inp.birth_year
    roth_start = inp.roth_start_age if inp.roth_start_age is not None else inp.retirement_age
    roth_end = inp.roth_end_age if inp.roth_end_age is not None else rmd_start_age(birth_year) - 1
    convert = inp.roth_conversion_rate is not None and inp.tax_mode == "progressive"
    rows: list[YearRow] = []

    for t, age in enumerate(_years(inp)):
        infl = (1 + inp.inflation) ** t
        retired = age >= inp.retirement_age
        r = returns[t] if returns is not None else _mean_return(inp, age)
        r = max(r, -0.95)

        income_by_type = dict.fromkeys(TAX_TYPES, 0.0)
        expenses = goals = 0.0
        goal_names: list[str] = []
        by_category: dict[str, float] = {}
        for f in inp.flows:
            if not f.active(age):
                continue
            nominal = f.amount * infl * (1 + f.real_growth) ** t
            if f.kind == "income":
                income_by_type[f.tax_type if f.tax_type in income_by_type else "ordinary"] += nominal
            elif f.kind == "goal":
                goals += nominal
                goal_names.append(f.name)
            else:
                expenses += nominal
                by_category[f.category] = by_category.get(f.category, 0.0) + nominal

        c_deferred = 0.0 if retired else inp.contrib_tax_deferred * infl
        c_free = 0.0 if retired else inp.contrib_tax_free * infl
        c_taxable = 0.0 if retired else inp.contrib_taxable * infl

        debt_payments = 0.0
        for d in debts:
            if d[0] <= 0:
                continue
            owed = d[0] * (1 + d[1])
            payment = min(d[2] * 12, owed)
            d[0] = owed - payment
            debt_payments += payment

        rmd = required_minimum_distribution(deferred, age, birth_year)
        deferred -= rmd
        people_65 = int(age >= 65)
        if inp.filing_status == "married_joint" and inp.spouse_current_age is not None:
            people_65 += int(inp.spouse_current_age + t >= 65)
        early = age < EARLY_WITHDRAWAL_AGE
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
            ceiling = bracket_ceiling(inp.roth_conversion_rate, inp.filing_status, infl)
            for _ in range(4):  # taxable Social Security rises with conversions, so iterate
                conversion = max(0.0, conversion + ceiling - ordinary_taxable_income(profile, year_income()))
            conversion = min(conversion, deferred)
            deferred -= conversion
            free += conversion

        tax = tax_for()
        income = sum(income_by_type.values())
        net = income + rmd - tax.total - expenses - goals - debt_payments - c_deferred - c_free - c_taxable

        deferred += c_deferred
        free += c_free
        taxable += c_taxable
        basis += c_taxable

        withdrawals = shortfall = realized = 0.0
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
                need -= gross - (tax.total - before)
                withdrawals += gross

            take = min(free, max(need, 0.0))
            free -= take
            need -= take
            withdrawals += take
            if need > 1.0:
                shortfall = need

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
                retired=retired,
                investment_return=r,
                income=income,
                taxes=tax.total,
                tax_federal=tax.federal,
                tax_state=tax.state,
                tax_fica=tax.fica,
                tax_penalty=tax.penalty,
                expenses=expenses,
                goals=goals,
                debt_payments=debt_payments,
                contributions=c_deferred + c_free + c_taxable,
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
    t = max(inp.retirement_age - inp.current_age, 0)
    spending = sum(
        f.amount * (1 + f.real_growth) ** t / max(f.every_n_years, 1)
        for f in inp.flows
        if f.kind == "expense" and f.start_age <= inp.retirement_age <= f.end_age
    )
    return spending / inp.withdrawal_rate


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def monte_carlo(inp: ProjectionInput, simulations: int = 1000, seed: int = 42) -> dict:
    rng = random.Random(seed)
    ages = list(_years(inp))
    means = [_mean_return(inp, age) for age in ages]
    by_year: list[list[float]] = [[] for _ in ages]
    successes = 0
    depletion_ages: list[int] = []

    for _ in range(simulations):
        returns = [rng.gauss(m, inp.return_volatility) for m in means]
        rows = simulate(inp, returns)
        failed_at = next((row.age for row in rows if row.shortfall > 0), None)
        if failed_at is None:
            successes += 1
        else:
            depletion_ages.append(failed_at)
        for i, row in enumerate(rows):
            by_year[i].append(row.investable_real)

    bands = []
    for age, values in zip(ages, by_year):
        values.sort()
        bands.append(
            {
                "age": age,
                "year": inp.start_year + age - inp.current_age,
                **{f"p{int(p * 100)}": _percentile(values, p) for p in (0.1, 0.25, 0.5, 0.75, 0.9)},
            }
        )
    depletion_ages.sort()
    return {
        "simulations": simulations,
        "success_rate": successes / simulations if simulations else 0.0,
        "median_depletion_age": _percentile(depletion_ages, 0.5) if depletion_ages else None,
        "bands": bands,
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
    }

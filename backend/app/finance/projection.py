"""Lifetime cash-flow projection and Monte Carlo simulation.

Inputs are expressed in today's dollars; the simulation runs in nominal dollars
(inflating flows each year) and reports both nominal and real (today's dollar) results.
Each simulated year applies cash flows first, then investment growth.
"""

import random
from dataclasses import asdict, dataclass, field

from .tax import EARLY_WITHDRAWAL_AGE, TaxBreakdown, TaxProfile, income_tax, required_minimum_distribution

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
    tax_deferred: float = 0.0
    tax_free: float = 0.0
    other_assets: float = 0.0
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
    net_cash_flow: float
    withdrawals: float
    shortfall: float
    cash: float
    taxable: float
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


def simulate(inp: ProjectionInput, returns: list[float] | None = None) -> list[YearRow]:
    cash, taxable, deferred, free = inp.cash, inp.taxable, inp.tax_deferred, inp.tax_free
    other = inp.other_assets
    debts = [[d.balance, d.apr, d.monthly_payment] for d in inp.debts]
    profile = inp.tax_profile
    birth_year = inp.birth_year
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

        def tax_for(extra_deferred: float) -> TaxBreakdown:
            return income_tax(
                profile,
                wages=income_by_type["wages"],
                ordinary=income_by_type["ordinary"],
                social_security=income_by_type["social_security"],
                pre_tax_contributions=c_deferred,
                deferred_withdrawals=rmd + extra_deferred,
                early_withdrawals=extra_deferred if early else 0.0,
                scale=infl,
                people_65_plus=people_65,
            )

        tax = tax_for(0.0)
        income = sum(income_by_type.values())
        net = income + rmd - tax.total - expenses - goals - debt_payments - c_deferred - c_free - c_taxable

        deferred += c_deferred
        free += c_free
        taxable += c_taxable

        withdrawals = shortfall = 0.0
        if net >= 0:
            taxable += net
        else:
            need = -net
            take = min(cash, need)
            cash -= take
            need -= take
            withdrawals += take

            take = min(taxable, need)
            taxable -= take
            need -= take
            withdrawals += take

            if need > 0 and deferred > 0:
                base = tax.total
                gross = need
                for _ in range(30):
                    nxt = need + tax_for(min(gross, deferred)).total - base
                    if abs(nxt - gross) < 0.001:
                        gross = nxt
                        break
                    gross = nxt
                gross = min(gross, deferred)
                tax = tax_for(gross)
                deferred -= gross
                need -= gross - (tax.total - base)
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
                net_cash_flow=net,
                withdrawals=withdrawals,
                shortfall=shortfall,
                cash=cash,
                taxable=taxable,
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


def project(inp: ProjectionInput, simulations: int = 1000, seed: int = 42) -> dict:
    rows = simulate(inp)
    target = fi_number(inp)
    fi_age = next((row.age for row in rows if target > 0 and row.investable_real >= target), None)
    depleted = next((row.age for row in rows if row.shortfall > 0), None)
    return {
        "fi_number": target,
        "fi_age": fi_age,
        "depletion_age": depleted,
        "lifetime_taxes_real": sum(
            row.taxes / (1 + inp.inflation) ** (row.age - inp.current_age) for row in rows
        ),
        "years": [asdict(row) for row in rows],
        "monte_carlo": monte_carlo(inp, simulations, seed) if simulations > 0 else None,
    }

"""Lifetime cash-flow projection and Monte Carlo simulation.

Inputs are expressed in today's dollars; the simulation runs in nominal dollars
(inflating flows each year) and reports both nominal and real (today's dollar) results.
Each simulated year applies cash flows first, then investment growth.
"""

import random
from dataclasses import asdict, dataclass, field


@dataclass
class FlowInput:
    name: str
    kind: str  # "income" | "expense" | "goal"
    amount: float  # annual, today's dollars
    start_age: int
    end_age: int  # inclusive
    real_growth: float = 0.0
    taxable: bool = True


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
    effective_tax_rate: float = 0.15
    withdrawal_rate: float = 0.04
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


@dataclass
class YearRow:
    year: int
    age: int
    retired: bool
    investment_return: float
    income: float
    taxes: float
    expenses: float
    goals: float
    debt_payments: float
    contributions: float
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


def _years(inp: ProjectionInput) -> range:
    return range(inp.current_age, inp.life_expectancy + 1)


def _mean_return(inp: ProjectionInput, age: int) -> float:
    return inp.retirement_return if age >= inp.retirement_age else inp.expected_return


def simulate(inp: ProjectionInput, returns: list[float] | None = None) -> list[YearRow]:
    cash, taxable, deferred, free = inp.cash, inp.taxable, inp.tax_deferred, inp.tax_free
    other = inp.other_assets
    debts = [[d.balance, d.apr, d.monthly_payment] for d in inp.debts]
    tax_rate = min(max(inp.effective_tax_rate, 0.0), 0.95)
    rows: list[YearRow] = []

    for t, age in enumerate(_years(inp)):
        infl = (1 + inp.inflation) ** t
        retired = age >= inp.retirement_age
        r = returns[t] if returns is not None else _mean_return(inp, age)
        r = max(r, -0.95)

        income_taxed = income_untaxed = expenses = goals = 0.0
        goal_names: list[str] = []
        for f in inp.flows:
            if not (f.start_age <= age <= f.end_age):
                continue
            nominal = f.amount * infl * (1 + f.real_growth) ** t
            if f.kind == "income":
                if f.taxable:
                    income_taxed += nominal
                else:
                    income_untaxed += nominal
            elif f.kind == "goal":
                goals += nominal
                goal_names.append(f.name)
            else:
                expenses += nominal

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

        taxes = tax_rate * max(0.0, income_taxed - c_deferred)
        income = income_taxed + income_untaxed
        net = income - taxes - expenses - goals - debt_payments - c_deferred - c_free - c_taxable

        deferred += c_deferred
        free += c_free
        taxable += c_taxable

        withdrawals = shortfall = 0.0
        if net >= 0:
            taxable += net
        else:
            need = -net
            for bucket in ("cash", "taxable", "tax_deferred", "tax_free"):
                if need <= 0:
                    break
                if bucket == "cash":
                    take = min(cash, need)
                    cash -= take
                    need -= take
                elif bucket == "taxable":
                    take = min(taxable, need)
                    taxable -= take
                    need -= take
                elif bucket == "tax_deferred":
                    gross = min(deferred, need / (1 - tax_rate))
                    deferred -= gross
                    taxes += gross * tax_rate
                    need -= gross * (1 - tax_rate)
                    take = gross
                else:
                    take = min(free, need)
                    free -= take
                    need -= take
                withdrawals += take
            if need > 0.01:
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
                taxes=taxes,
                expenses=expenses,
                goals=goals,
                debt_payments=debt_payments,
                contributions=c_deferred + c_free + c_taxable,
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
            )
        )
    return rows


def fi_number(inp: ProjectionInput) -> float:
    """Investable assets (today's dollars) needed to cover first-year retirement spending at the withdrawal rate."""
    if inp.withdrawal_rate <= 0:
        return 0.0
    t = max(inp.retirement_age - inp.current_age, 0)
    spending = sum(
        f.amount * (1 + f.real_growth) ** t
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
    result = {
        "fi_number": target,
        "fi_age": fi_age,
        "depletion_age": depleted,
        "years": [asdict(row) for row in rows],
        "monte_carlo": monte_carlo(inp, simulations, seed) if simulations > 0 else None,
    }
    return result

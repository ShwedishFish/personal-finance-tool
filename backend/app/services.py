from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .finance.projection import DebtInput, FlowInput, ProjectionInput
from .models import Account, Plan

INVESTMENT_KINDS = {"brokerage", "retirement"}
OTHER_ASSET_KINDS = {"property", "other_asset"}


def active_accounts(session: Session) -> list[Account]:
    return list(session.scalars(select(Account).where(Account.archived.is_(False)).order_by(Account.name)))


def build_projection_input(plan: Plan, accounts: list[Account], today: date | None = None) -> tuple[ProjectionInput, list[str]]:
    today = today or date.today()
    current_age = today.year - plan.birth_year
    warnings: list[str] = []
    if current_age >= plan.life_expectancy:
        warnings.append("Life expectancy is not after your current age; the projection is empty.")
    if plan.retirement_age < current_age:
        warnings.append("Retirement age is in the past; the plan treats you as already retired.")

    inp = ProjectionInput(
        current_age=current_age,
        retirement_age=plan.retirement_age,
        life_expectancy=plan.life_expectancy,
        start_year=today.year,
        inflation=plan.inflation,
        expected_return=plan.expected_return,
        retirement_return=plan.retirement_return,
        return_volatility=plan.return_volatility,
        cash_return=plan.cash_return,
        effective_tax_rate=plan.effective_tax_rate,
        withdrawal_rate=plan.withdrawal_rate,
    )

    for acct in accounts:
        balance = acct.latest_balance
        if acct.is_liability:
            debt = abs(balance)
            if debt > 0 and acct.monthly_payment <= 0:
                warnings.append(f"'{acct.name}' has no monthly payment set, so its balance only grows.")
            inp.debts.append(DebtInput(acct.name, debt, acct.interest_rate, acct.monthly_payment))
            continue
        if acct.kind == "cash":
            inp.cash += balance
            inp.contrib_taxable += acct.annual_contribution
        elif acct.kind in OTHER_ASSET_KINDS or acct.tax_treatment == "none":
            inp.other_assets += balance
        elif acct.tax_treatment == "tax_deferred":
            inp.tax_deferred += balance
            inp.contrib_tax_deferred += acct.annual_contribution
        elif acct.tax_treatment == "tax_free":
            inp.tax_free += balance
            inp.contrib_tax_free += acct.annual_contribution
        else:
            inp.taxable += balance
            inp.contrib_taxable += acct.annual_contribution

    for cf in plan.cash_flows:
        start = plan.retirement_age if cf.starts_at_retirement else (cf.start_age if cf.start_age is not None else current_age)
        if cf.ends_at_retirement:
            end = plan.retirement_age - 1
        elif cf.end_age is not None:
            end = cf.end_age
        elif cf.kind == "goal":
            end = start
        else:
            end = plan.life_expectancy
        if end < start:
            warnings.append(f"'{cf.name}' ends before it starts and is ignored.")
            continue
        inp.flows.append(FlowInput(cf.name, cf.kind, cf.amount, start, end, cf.real_growth, cf.taxable))

    if not any(f.kind == "expense" for f in inp.flows):
        warnings.append("No living expenses are entered, so the plan cannot compute a FI number.")
    return inp, warnings

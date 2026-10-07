from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .finance.projection import DebtInput, FlowInput, ProjectionInput
from .finance.social_security import annual_benefit, spousal_top_up
from .models import Account, Child, Plan

INVESTMENT_KINDS = {"brokerage", "retirement"}
OTHER_ASSET_KINDS = {"property", "other_asset"}


def active_accounts(session: Session) -> list[Account]:
    return list(session.scalars(select(Account).where(Account.archived.is_(False)).order_by(Account.name)))


CHILD_STAGES = (("ages 0–5", 0, 5, "cost_early"), ("ages 6–12", 6, 12, "cost_middle"), ("ages 13–17", 13, 17, "cost_teen"))


def child_flows(child: Child, parent_birth_year: int) -> list[FlowInput]:
    """Expense items for each life stage of a child, expressed in the plan owner's ages."""
    offset = child.birth_year - parent_birth_year
    flows = []
    for label, lo, hi, attr in CHILD_STAGES:
        cost = getattr(child, attr)
        if cost > 0:
            flows.append(FlowInput(f"{child.name}: {label}", "expense", cost, offset + lo, offset + hi, category="kids"))
    if child.college_cost > 0 and child.college_years > 0:
        start = offset + child.college_start_age
        flows.append(
            FlowInput(
                f"{child.name}: college", "expense", child.college_cost, start, start + child.college_years - 1,
                category="education",
            )
        )
    return flows


def social_security_flows(plan: Plan, current_age: int, claim_age: int | None = None) -> list[FlowInput]:
    """Benefits for the plan owner and spouse, with start ages expressed in the owner's age."""
    my_claim = claim_age if claim_age is not None else plan.ss_claim_age
    flows = []

    def add(name: str, annual: float, start: int) -> None:
        if annual > 0:
            flows.append(
                FlowInput(name, "income", annual, max(start, current_age), plan.life_expectancy,
                          tax_type="social_security")
            )

    add("Social Security", annual_benefit(plan.ss_monthly_benefit, plan.birth_year, my_claim), my_claim)
    if not plan.spouse_birth_year:
        return flows

    offset = plan.spouse_birth_year - plan.birth_year
    spouse_claim = plan.spouse_ss_claim_age + offset  # in the owner's age
    add(
        "Social Security (spouse)",
        annual_benefit(plan.spouse_ss_monthly_benefit, plan.spouse_birth_year, plan.spouse_ss_claim_age),
        spouse_claim,
    )
    both_claimed = max(my_claim, spouse_claim)
    add(
        "Spousal benefit (spouse)",
        spousal_top_up(plan.spouse_ss_monthly_benefit, plan.ss_monthly_benefit, plan.spouse_birth_year,
                       plan.spouse_ss_claim_age),
        both_claimed,
    )
    add(
        "Spousal benefit (you)",
        spousal_top_up(plan.ss_monthly_benefit, plan.spouse_ss_monthly_benefit, plan.birth_year, my_claim),
        both_claimed,
    )
    return flows


_PLAN = object()  # sentinel: use the plan's own Roth conversion setting


def build_projection_input(
    plan: Plan,
    accounts: list[Account],
    today: date | None = None,
    ss_claim_age: int | None = None,
    roth_rate: float | None | object = _PLAN,
) -> tuple[ProjectionInput, list[str]]:
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
        tax_mode=plan.tax_mode,
        filing_status=plan.filing_status,
        effective_tax_rate=plan.effective_tax_rate,
        state_tax_rate=plan.state_tax_rate,
        withdrawal_rate=plan.withdrawal_rate,
        spouse_current_age=today.year - plan.spouse_birth_year if plan.spouse_birth_year else None,
        roth_conversion_rate=plan.roth_conversion_rate if roth_rate is _PLAN else roth_rate,
        roth_start_age=plan.roth_start_age,
        roth_end_age=plan.roth_end_age,
    )
    if inp.roth_conversion_rate is not None and plan.tax_mode == "flat":
        warnings.append("Roth conversions need the bracket tax model; they are skipped with a flat rate.")
    taxable_basis = 0.0

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
            taxable_basis += balance if acct.cost_basis is None else acct.cost_basis
            inp.contrib_taxable += acct.annual_contribution
    inp.taxable_basis = taxable_basis

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
        inp.flows.append(
            FlowInput(
                cf.name, cf.kind, cf.amount, start, end, cf.real_growth, cf.tax_type, cf.category, cf.every_n_years
            )
        )

    for child in plan.children:
        inp.flows.extend(child_flows(child, plan.birth_year))

    ss_flows = social_security_flows(plan, current_age, ss_claim_age)
    if ss_flows and any(f.tax_type == "social_security" for f in inp.flows):
        warnings.append(
            "Social Security is set on the plan and also entered as an income item; it may be counted twice."
        )
    inp.flows.extend(ss_flows)

    if not any(f.kind == "expense" and f.category not in ("kids", "education") for f in inp.flows):
        warnings.append("No living expenses are entered, so the plan cannot compute a FI number.")
    return inp, warnings

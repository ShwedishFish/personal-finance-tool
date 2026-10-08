from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .finance.medicare import MEDICARE_AGE
from .finance.projection import DebtInput, FlowInput, ProjectionInput
from .finance.social_security import annual_benefit, spousal_top_up
from .models import Account, Child, Plan

INVESTMENT_KINDS = {"brokerage", "retirement"}
OTHER_ASSET_KINDS = {"property", "other_asset"}


def active_accounts(session: Session) -> list[Account]:
    return list(session.scalars(select(Account).where(Account.archived.is_(False)).order_by(Account.name)))


CHILD_STAGES = (
    ("ages 0–5", 0, 5, "cost_early"),
    ("ages 6–12", 6, 12, "cost_middle"),
    ("ages 13–17", 13, 17, "cost_teen"),
)


def child_flows(child: Child, parent_birth_year: int) -> list[FlowInput]:
    """Expense items for each life stage of a child, expressed in the plan owner's ages."""
    offset = child.birth_year - parent_birth_year
    flows = []
    for label, lo, hi, attr in CHILD_STAGES:
        cost = getattr(child, attr)
        if cost > 0:
            flows.append(
                FlowInput(f"{child.name}: {label}", "expense", cost, offset + lo, offset + hi, category="kids")
            )
    if child.college_cost > 0 and child.college_years > 0:
        start = offset + child.college_start_age
        flows.append(
            FlowInput(
                f"{child.name}: college", "expense", child.college_cost, start, start + child.college_years - 1,
                category="education",
            )
        )
    return flows


def plan_end_age(plan: Plan) -> int:
    """Last year of the plan in the owner's age: the later of the two life expectancies."""
    if not plan.spouse_birth_year:
        return plan.life_expectancy
    return max(plan.life_expectancy, plan.spouse_life_expectancy + plan.spouse_birth_year - plan.birth_year)


def social_security_flows(plan: Plan, current_age: int, claim_age: int | None = None) -> list[FlowInput]:
    """Benefits for the plan owner and spouse, with start ages expressed in the owner's age."""
    my_claim = claim_age if claim_age is not None else plan.ss_claim_age
    end = plan_end_age(plan)
    flows = []

    def add(name: str, annual: float, start: int, owner: str, spousal: bool = False) -> None:
        if annual > 0:
            flows.append(
                FlowInput(name, "income", annual, max(start, current_age), end, tax_type="social_security",
                          owner=owner, spousal=spousal)
            )

    add("Social Security", annual_benefit(plan.ss_monthly_benefit, plan.birth_year, my_claim), my_claim, "self")
    if not plan.spouse_birth_year:
        return flows

    offset = plan.spouse_birth_year - plan.birth_year
    spouse_claim = plan.spouse_ss_claim_age + offset  # in the owner's age
    add(
        "Social Security (spouse)",
        annual_benefit(plan.spouse_ss_monthly_benefit, plan.spouse_birth_year, plan.spouse_ss_claim_age),
        spouse_claim,
        "spouse",
    )
    both_claimed = max(my_claim, spouse_claim)
    add(
        "Spousal benefit (spouse)",
        spousal_top_up(plan.spouse_ss_monthly_benefit, plan.ss_monthly_benefit, plan.spouse_birth_year,
                       plan.spouse_ss_claim_age),
        both_claimed,
        "spouse",
        spousal=True,
    )
    add(
        "Spousal benefit (you)",
        spousal_top_up(plan.ss_monthly_benefit, plan.spouse_ss_monthly_benefit, plan.birth_year, my_claim),
        both_claimed,
        "self",
        spousal=True,
    )
    return flows


def spouse_offset(plan: Plan) -> int:
    """Add to a spouse's age to get your age in the same year."""
    return plan.spouse_birth_year - plan.birth_year if plan.spouse_birth_year else 0


def spouse_retirement_in_your_age(plan: Plan, retirement_age: int) -> int:
    if not plan.spouse_birth_year or plan.spouse_retirement_age is None:
        return retirement_age
    return plan.spouse_retirement_age + spouse_offset(plan)


def healthcare_flows(plan: Plan, current_age: int, retirement_age: int) -> list[FlowInput]:
    """Per-person health costs from each person's retirement: private insurance until Medicare, then
    Medicare-era costs. While working, coverage is assumed to come through work and regular spending.
    """
    people = [("", "self", 0, retirement_age)]
    if plan.spouse_birth_year:
        people.append((" (spouse)", "spouse", spouse_offset(plan), spouse_retirement_in_your_age(plan, retirement_age)))
    end = plan_end_age(plan)
    flows = []
    for suffix, owner, offset, retires in people:
        medicare_start = MEDICARE_AGE + offset  # in your age
        pre_start = max(retires, current_age)
        if plan.pre_medicare_cost > 0 and pre_start < medicare_start:
            flows.append(
                FlowInput(f"Health insurance before Medicare{suffix}", "expense", plan.pre_medicare_cost,
                          pre_start, medicare_start - 1, plan.health_cost_growth, category="healthcare", owner=owner)
            )
        if plan.medicare_cost > 0:
            flows.append(
                FlowInput(f"Medicare premiums & out-of-pocket{suffix}", "expense", plan.medicare_cost,
                          max(medicare_start, current_age), end, plan.health_cost_growth, category="healthcare",
                          owner=owner)
            )
    return flows


_PLAN = object()  # sentinel: use the plan's own Roth conversion setting


def build_projection_input(
    plan: Plan,
    accounts: list[Account],
    today: date | None = None,
    ss_claim_age: int | None = None,
    roth_rate: float | None | object = _PLAN,
    retirement_age: int | None = None,
) -> tuple[ProjectionInput, list[str]]:
    today = today or date.today()
    current_age = today.year - plan.birth_year
    retirement_age = plan.retirement_age if retirement_age is None else retirement_age
    end_age = plan_end_age(plan)
    warnings: list[str] = []
    if current_age >= plan.life_expectancy:
        warnings.append("Life expectancy is not after your current age; the projection is empty.")
    if retirement_age < current_age:
        warnings.append("Retirement age is in the past; the plan treats you as already retired.")

    inp = ProjectionInput(
        current_age=current_age,
        retirement_age=retirement_age,
        life_expectancy=plan.life_expectancy,
        start_year=today.year,
        inflation=plan.inflation,
        expected_return=plan.expected_return,
        retirement_return=plan.retirement_return,
        return_volatility=plan.return_volatility,
        return_model=plan.return_model,
        stock_return=plan.stock_return,
        bond_return=plan.bond_return,
        stock_volatility=plan.stock_volatility,
        bond_volatility=plan.bond_volatility,
        stock_bond_correlation=plan.stock_bond_correlation,
        stock_allocation_now=plan.stock_allocation_now,
        stock_allocation_retired=plan.stock_allocation_retired,
        cash_return=plan.cash_return,
        tax_mode=plan.tax_mode,
        filing_status=plan.filing_status,
        effective_tax_rate=plan.effective_tax_rate,
        state_tax_rate=plan.state_tax_rate,
        withdrawal_rate=plan.withdrawal_rate,
        spouse_current_age=today.year - plan.spouse_birth_year if plan.spouse_birth_year else None,
        spouse_life_expectancy=plan.spouse_life_expectancy if plan.spouse_birth_year else None,
        spouse_retirement_age=plan.spouse_retirement_age if plan.spouse_birth_year else None,
        survivor_spending=plan.survivor_spending,
        roth_conversion_rate=plan.roth_conversion_rate if roth_rate is _PLAN else roth_rate,
        roth_start_age=plan.roth_start_age,
        roth_end_age=plan.roth_end_age,
    )
    if inp.roth_conversion_rate is not None and plan.tax_mode == "flat":
        warnings.append("Roth conversions need the bracket tax model; they are skipped with a flat rate.")
    taxable_basis = 0.0
    has_spouse = bool(plan.spouse_birth_year)
    spouse_retires = spouse_retirement_in_your_age(plan, retirement_age)
    if has_spouse and plan.spouse_retirement_age is not None and spouse_retires < current_age:
        warnings.append("Your spouse's retirement age is in the past; the plan treats them as already retired.")

    for acct in accounts:
        balance = acct.latest_balance
        if acct.is_liability:
            debt = abs(balance)
            if debt > 0 and acct.monthly_payment <= 0:
                warnings.append(f"'{acct.name}' has no monthly payment set, so its balance only grows.")
            inp.debts.append(DebtInput(acct.name, debt, acct.interest_rate, acct.monthly_payment))
            continue
        prefix = "spouse_contrib_" if acct.owner == "spouse" and has_spouse else "contrib_"
        if acct.kind == "cash":
            inp.cash += balance
            bucket = "taxable"
        elif acct.kind in OTHER_ASSET_KINDS or acct.tax_treatment == "none":
            inp.other_assets += balance
            continue
        elif acct.tax_treatment == "tax_deferred":
            inp.tax_deferred += balance
            bucket = "tax_deferred"
        elif acct.tax_treatment == "tax_free":
            inp.tax_free += balance
            bucket = "tax_free"
        else:
            inp.taxable += balance
            taxable_basis += balance if acct.cost_basis is None else acct.cost_basis
            bucket = "taxable"
        setattr(inp, prefix + bucket, getattr(inp, prefix + bucket) + acct.annual_contribution)
    inp.taxable_basis = taxable_basis

    offset = spouse_offset(plan)
    for cf in plan.cash_flows:
        owner = cf.owner if cf.owner in ("self", "spouse") else ""
        if owner == "spouse" and not has_spouse:
            warnings.append(f"'{cf.name}' belongs to your spouse, but no spouse is set; it is treated as joint.")
            owner = ""
        # Spouse items are entered in the spouse's age; the engine works in yours.
        shift = offset if owner == "spouse" else 0
        retires = spouse_retires if owner == "spouse" else retirement_age
        if cf.starts_at_retirement:
            start = retires
        elif cf.start_age is not None:
            start = cf.start_age + shift
        else:
            start = current_age
        if cf.ends_at_retirement:
            end = retires - 1
        elif cf.end_age is not None:
            end = cf.end_age + shift
        elif cf.kind == "goal":
            end = start
        else:
            end = end_age
        if end < start:
            warnings.append(f"'{cf.name}' ends before it starts and is ignored.")
            continue
        inp.flows.append(
            FlowInput(
                cf.name, cf.kind, cf.amount, start, end, cf.real_growth, cf.tax_type, cf.category, cf.every_n_years,
                owner=owner,
            )
        )

    for child in plan.children:
        inp.flows.extend(child_flows(child, plan.birth_year))

    health = healthcare_flows(plan, current_age, retirement_age)
    if health and any(cf.kind == "expense" and cf.category == "healthcare" for cf in plan.cash_flows):
        warnings.append(
            "You have a Healthcare spending item and retirement healthcare costs set under Healthcare; "
            "they may overlap."
        )
    inp.flows.extend(health)

    ss_flows = social_security_flows(plan, current_age, ss_claim_age)
    if ss_flows and any(f.tax_type == "social_security" for f in inp.flows):
        warnings.append(
            "Social Security is set on the plan and also entered as an income item; it may be counted twice."
        )
    inp.flows.extend(ss_flows)

    if not any(cf.kind == "expense" and cf.category not in ("kids", "education") for cf in plan.cash_flows):
        warnings.append("No living expenses are entered, so the plan cannot compute a FI number.")
    return inp, warnings

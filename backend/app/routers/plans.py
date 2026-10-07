from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import apply_update, get_session
from ..finance.projection import monte_carlo, project, simulate
from ..finance.social_security import (
    EARLIEST_CLAIM_AGE,
    LATEST_CLAIM_AGE,
    annual_benefit,
    full_retirement_age_months,
)
from ..models import CashFlow, Child, Plan
from ..schemas import (
    CashFlowCreate,
    CashFlowOut,
    CashFlowUpdate,
    ChildCreate,
    ChildOut,
    ChildUpdate,
    PlanCreate,
    PlanOut,
    PlanUpdate,
)
from ..services import active_accounts, build_projection_input, social_security_flows

router = APIRouter(prefix="/api", tags=["plans"])


def get_plan(session: Session, plan_id: int) -> Plan:
    plan = session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(404, "Plan not found")
    return plan


@router.get("/plans", response_model=list[PlanOut])
def list_plans(session: Session = Depends(get_session)):
    return list(session.scalars(select(Plan).order_by(Plan.created_at)))


@router.post("/plans", response_model=PlanOut, status_code=201)
def create_plan(body: PlanCreate, session: Session = Depends(get_session)):
    plan = Plan(**body.model_dump())
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


@router.get("/plans/{plan_id}", response_model=PlanOut)
def read_plan(plan_id: int, session: Session = Depends(get_session)):
    return get_plan(session, plan_id)


@router.patch("/plans/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, body: PlanUpdate, session: Session = Depends(get_session)):
    plan = get_plan(session, plan_id)
    apply_update(plan, body.model_dump(exclude_unset=True))
    session.commit()
    session.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: int, session: Session = Depends(get_session)):
    session.delete(get_plan(session, plan_id))
    session.commit()


@router.post("/plans/{plan_id}/duplicate", response_model=PlanOut, status_code=201)
def duplicate_plan(plan_id: int, session: Session = Depends(get_session)):
    src = get_plan(session, plan_id)
    fields = PlanCreate.model_validate(src, from_attributes=True).model_dump()
    fields["name"] = f"{src.name} (copy)"
    copy = Plan(**fields)
    for cf in src.cash_flows:
        copy.cash_flows.append(CashFlow(**CashFlowCreate.model_validate(cf, from_attributes=True).model_dump()))
    for child in src.children:
        copy.children.append(Child(**ChildCreate.model_validate(child, from_attributes=True).model_dump()))
    session.add(copy)
    session.commit()
    session.refresh(copy)
    return copy


@router.post("/plans/{plan_id}/cash-flows", response_model=CashFlowOut, status_code=201)
def add_cash_flow(plan_id: int, body: CashFlowCreate, session: Session = Depends(get_session)):
    plan = get_plan(session, plan_id)
    cf = CashFlow(plan_id=plan.id, **body.model_dump())
    session.add(cf)
    session.commit()
    session.refresh(cf)
    return cf


@router.patch("/cash-flows/{cash_flow_id}", response_model=CashFlowOut)
def update_cash_flow(cash_flow_id: int, body: CashFlowUpdate, session: Session = Depends(get_session)):
    cf = session.get(CashFlow, cash_flow_id)
    if cf is None:
        raise HTTPException(404, "Cash flow not found")
    apply_update(cf, body.model_dump(exclude_unset=True))
    session.commit()
    session.refresh(cf)
    return cf


@router.delete("/cash-flows/{cash_flow_id}", status_code=204)
def delete_cash_flow(cash_flow_id: int, session: Session = Depends(get_session)):
    cf = session.get(CashFlow, cash_flow_id)
    if cf is None:
        raise HTTPException(404, "Cash flow not found")
    session.delete(cf)
    session.commit()


@router.post("/plans/{plan_id}/children", response_model=ChildOut, status_code=201)
def add_child(plan_id: int, body: ChildCreate, session: Session = Depends(get_session)):
    plan = get_plan(session, plan_id)
    child = Child(plan_id=plan.id, **body.model_dump())
    session.add(child)
    session.commit()
    session.refresh(child)
    return child


@router.patch("/children/{child_id}", response_model=ChildOut)
def update_child(child_id: int, body: ChildUpdate, session: Session = Depends(get_session)):
    child = session.get(Child, child_id)
    if child is None:
        raise HTTPException(404, "Child not found")
    apply_update(child, body.model_dump(exclude_unset=True))
    session.commit()
    session.refresh(child)
    return child


@router.delete("/children/{child_id}", status_code=204)
def delete_child(child_id: int, session: Session = Depends(get_session)):
    child = session.get(Child, child_id)
    if child is None:
        raise HTTPException(404, "Child not found")
    session.delete(child)
    session.commit()


@router.get("/plans/{plan_id}/social-security")
def social_security_comparison(
    plan_id: int,
    simulations: int = Query(300, ge=50, le=2000),
    session: Session = Depends(get_session),
):
    """Run the whole plan once per possible claiming age and compare outcomes."""
    plan = get_plan(session, plan_id)
    if plan.ss_monthly_benefit <= 0:
        raise HTTPException(400, "Enter your Social Security benefit at full retirement age first.")
    accounts = active_accounts(session)
    current_age = date.today().year - plan.birth_year
    options = []
    for claim_age in range(max(EARLIEST_CLAIM_AGE, current_age), LATEST_CLAIM_AGE + 1):
        inp, _ = build_projection_input(plan, accounts, ss_claim_age=claim_age)
        expected = simulate(inp)
        mc = monte_carlo(inp, simulations=simulations)
        annual = annual_benefit(plan.ss_monthly_benefit, plan.birth_year, claim_age)
        options.append(
            {
                "claim_age": claim_age,
                "monthly_benefit": annual / 12,
                "lifetime_benefits": annual * max(plan.life_expectancy - claim_age + 1, 0),
                "success_rate": mc["success_rate"],
                "median_ending_real": mc["bands"][-1]["p50"] if mc["bands"] else 0.0,
                "expected_ending_real": expected[-1].investable_real if expected else 0.0,
            }
        )
    best = max(options, key=lambda o: (round(o["success_rate"], 2), o["median_ending_real"]), default=None)
    return {
        "full_retirement_age": full_retirement_age_months(plan.birth_year) / 12,
        "current_claim_age": plan.ss_claim_age,
        "best_claim_age": best["claim_age"] if best else None,
        "options": options,
    }


@router.get("/plans/{plan_id}/projection")
def plan_projection(
    plan_id: int,
    simulations: int = Query(1000, ge=0, le=10000),
    seed: int = 42,
    session: Session = Depends(get_session),
):
    plan = get_plan(session, plan_id)
    inp, warnings = build_projection_input(plan, active_accounts(session))
    result = project(inp, simulations=simulations, seed=seed)
    result["warnings"] = warnings
    result["social_security"] = [
        {"name": f.name, "start_age": f.start_age, "annual": f.amount}
        for f in social_security_flows(plan, inp.current_age)
    ]
    result["starting"] = {
        "age": inp.current_age,
        "cash": inp.cash,
        "taxable": inp.taxable,
        "tax_deferred": inp.tax_deferred,
        "tax_free": inp.tax_free,
        "other_assets": inp.other_assets,
        "liabilities": sum(d.balance for d in inp.debts),
    }
    return result

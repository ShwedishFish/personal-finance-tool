from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..finance.projection import project
from ..models import CashFlow, Plan
from ..schemas import CashFlowCreate, CashFlowOut, CashFlowUpdate, PlanCreate, PlanOut, PlanUpdate
from ..services import active_accounts, build_projection_input

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
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(plan, key, value)
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
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(cf, key, value)
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

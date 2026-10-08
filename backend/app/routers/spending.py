from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..finance.projection import simulate
from ..models import CategoryRule, Plan, Transaction
from ..services import active_accounts, build_projection_input
from ..transactions import CATEGORIES, import_csv, set_category, spending_summary

router = APIRouter(prefix="/api", tags=["spending"])

Category = Literal[CATEGORIES]  # type: ignore[valid-type]


class TransactionImport(BaseModel):
    csv: str = Field(max_length=10_000_000)
    negative_is_spending: bool = True


class TransactionUpdate(BaseModel):
    category: Category
    remember: bool = False  # also recategorize this merchant's other transactions, now and in future


def _out(t: Transaction) -> dict:
    return {
        "id": t.id,
        "date": t.posted_on.isoformat(),
        "description": t.description,
        "merchant": t.merchant,
        "amount": t.amount,
        "category": t.category,
        "category_source": t.category_source,
        "account": t.account.name if t.account else None,
        "pending": t.pending,
        "source": "csv" if (t.external_id or "").startswith("csv:") else "plaid",
    }


@router.get("/transactions")
def list_transactions(
    start: date | None = None,
    end: date | None = None,
    category: str | None = None,
    q: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    session: Session = Depends(get_session),
):
    query = select(Transaction).order_by(Transaction.posted_on.desc(), Transaction.id.desc())
    if start:
        query = query.where(Transaction.posted_on >= start)
    if end:
        query = query.where(Transaction.posted_on <= end)
    if category:
        query = query.where(Transaction.category == category)
    if q:
        like = f"%{q}%"
        query = query.where(Transaction.description.ilike(like) | Transaction.merchant.ilike(like))
    return [_out(t) for t in session.scalars(query.limit(limit))]


@router.patch("/transactions/{txn_id}")
def update_transaction(txn_id: int, body: TransactionUpdate, session: Session = Depends(get_session)):
    txn = session.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    return {"updated": set_category(session, txn, body.category, body.remember)}


@router.delete("/transactions/imported", status_code=204)
def delete_imported(session: Session = Depends(get_session)):
    session.execute(delete(Transaction).where(Transaction.external_id.like("csv:%")))
    session.commit()


@router.delete("/transactions/{txn_id}", status_code=204)
def delete_transaction(txn_id: int, session: Session = Depends(get_session)):
    txn = session.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    session.delete(txn)
    session.commit()


@router.post("/import/transactions")
def import_transactions(body: TransactionImport, session: Session = Depends(get_session)):
    try:
        return import_csv(session, body.csv, body.negative_is_spending)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err


@router.get("/spending/summary")
def summary(
    months: int = Query(12, ge=1, le=60),
    plan_id: int | None = None,
    session: Session = Depends(get_session),
):
    planned = None
    if plan_id is not None:
        plan = session.get(Plan, plan_id)
        if plan is None:
            raise HTTPException(404, "Plan not found")
        inp, _ = build_projection_input(plan, active_accounts(session))
        rows = simulate(inp)
        planned = rows[0].expenses_by_category_real if rows else {}
    return spending_summary(session, months, planned=planned)


@router.get("/spending/rules")
def list_rules(session: Session = Depends(get_session)):
    rules = session.scalars(select(CategoryRule).order_by(CategoryRule.match))
    return [{"id": r.id, "match": r.match, "category": r.category} for r in rules]


@router.delete("/spending/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, session: Session = Depends(get_session)):
    rule = session.get(CategoryRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    session.delete(rule)
    session.commit()

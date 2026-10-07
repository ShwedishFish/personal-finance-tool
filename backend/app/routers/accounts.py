from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Account, BalanceSnapshot
from ..schemas import AccountCreate, AccountOut, AccountUpdate, BalanceIn, BalanceOut

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def to_out(acct: Account) -> AccountOut:
    out = AccountOut.model_validate(acct)
    out.linked = acct.plaid_account_id is not None
    return out


def get_account(session: Session, account_id: int) -> Account:
    acct = session.get(Account, account_id)
    if acct is None:
        raise HTTPException(404, "Account not found")
    return acct


def upsert_balance(session: Session, acct: Account, balance: float, as_of: date) -> BalanceSnapshot:
    snap = session.scalar(
        select(BalanceSnapshot).where(BalanceSnapshot.account_id == acct.id, BalanceSnapshot.as_of == as_of)
    )
    if acct.is_liability:
        balance = abs(balance)
    if snap:
        snap.balance = balance
    else:
        snap = BalanceSnapshot(account_id=acct.id, as_of=as_of, balance=balance)
        session.add(snap)
    return snap


@router.get("", response_model=list[AccountOut])
def list_accounts(include_archived: bool = False, session: Session = Depends(get_session)):
    query = select(Account).order_by(Account.name)
    if not include_archived:
        query = query.where(Account.archived.is_(False))
    return [to_out(a) for a in session.scalars(query)]


@router.post("", response_model=AccountOut, status_code=201)
def create_account(body: AccountCreate, session: Session = Depends(get_session)):
    data = body.model_dump(exclude={"balance", "as_of"})
    acct = Account(**data)
    session.add(acct)
    session.flush()
    if body.balance is not None:
        upsert_balance(session, acct, body.balance, body.as_of or date.today())
    session.commit()
    session.refresh(acct)
    return to_out(acct)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountUpdate, session: Session = Depends(get_session)):
    acct = get_account(session, account_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(acct, key, value)
    session.commit()
    session.refresh(acct)
    return to_out(acct)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, session: Session = Depends(get_session)):
    session.delete(get_account(session, account_id))
    session.commit()


@router.get("/{account_id}/balances", response_model=list[BalanceOut])
def list_balances(account_id: int, session: Session = Depends(get_session)):
    return get_account(session, account_id).balances


@router.post("/{account_id}/balances", response_model=BalanceOut, status_code=201)
def add_balance(account_id: int, body: BalanceIn, session: Session = Depends(get_session)):
    acct = get_account(session, account_id)
    snap = upsert_balance(session, acct, body.balance, body.as_of or date.today())
    session.commit()
    session.refresh(snap)
    return snap


@router.delete("/{account_id}/balances/{balance_id}", status_code=204)
def delete_balance(account_id: int, balance_id: int, session: Session = Depends(get_session)):
    snap = session.get(BalanceSnapshot, balance_id)
    if snap is None or snap.account_id != account_id:
        raise HTTPException(404, "Balance not found")
    session.delete(snap)
    session.commit()

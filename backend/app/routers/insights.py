from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..finance.debt import Debt, payoff_plan
from ..finance.networth import Snapshot, allocation, net_worth_history
from ..models import Account, BalanceSnapshot
from ..schemas import DebtPayoffRequest
from ..services import active_accounts

router = APIRouter(prefix="/api", tags=["insights"])

KIND_ASSET_CLASS = {"cash": "cash", "property": "real_estate", "other_asset": "other"}


@router.get("/net-worth")
def net_worth(session: Session = Depends(get_session)):
    accounts = active_accounts(session)
    by_kind: dict[str, float] = defaultdict(float)
    assets = liabilities = 0.0
    for acct in accounts:
        if acct.is_liability:
            liabilities += abs(acct.latest_balance)
            by_kind[acct.kind] -= abs(acct.latest_balance)
        else:
            assets += acct.latest_balance
            by_kind[acct.kind] += acct.latest_balance

    rows = session.execute(
        select(BalanceSnapshot, Account)
        .join(Account, BalanceSnapshot.account_id == Account.id)
        .where(Account.archived.is_(False))
    ).all()
    snapshots = [Snapshot(s.account_id, s.as_of, s.balance, a.is_liability) for s, a in rows]
    return {
        "assets": assets,
        "liabilities": liabilities,
        "net_worth": assets - liabilities,
        "by_kind": dict(by_kind),
        "history": net_worth_history(snapshots),
    }


@router.get("/allocation")
def asset_allocation(session: Session = Depends(get_session)):
    items: list[tuple[str, float]] = []
    for acct in active_accounts(session):
        if acct.is_liability:
            continue
        if acct.holdings:
            items.extend((h.asset_class, h.value) for h in acct.holdings)
        else:
            items.append((KIND_ASSET_CLASS.get(acct.kind, "unclassified_investments"), acct.latest_balance))
    return allocation(items)


@router.post("/debt/payoff")
def debt_payoff(body: DebtPayoffRequest, session: Session = Depends(get_session)):
    accounts = [a for a in active_accounts(session) if a.is_liability and abs(a.latest_balance) > 0]
    if body.account_ids is not None:
        accounts = [a for a in accounts if a.id in body.account_ids]
    debts = [Debt(a.name, abs(a.latest_balance), a.interest_rate, a.monthly_payment) for a in accounts]
    result = payoff_plan(debts, body.extra_monthly, body.strategy)
    other = "snowball" if body.strategy == "avalanche" else "avalanche"
    alt = payoff_plan(debts, body.extra_monthly, other)
    result["comparison"] = {"strategy": other, "months": alt["months"], "total_interest": alt["total_interest"]}
    return result

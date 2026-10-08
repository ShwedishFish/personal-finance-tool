import csv
import io
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ACCOUNT_KINDS, Account, BalanceSnapshot, CashFlow, Child, Holding, PlaidItem, Plan
from ..schemas import AccountBase, CashFlowCreate, ChildCreate, PlanCreate
from .accounts import upsert_balance

router = APIRouter(prefix="/api", tags=["data"])

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d")
TAX_TREATMENTS = ("taxable", "tax_deferred", "tax_free", "none")
REQUIRED_COLUMNS = ("date", "account", "balance")


class BalanceImport(BaseModel):
    csv: str = Field(max_length=5_000_000)
    create_missing: bool = True


def parse_date(value: str) -> date:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{value}' (use YYYY-MM-DD or MM/DD/YYYY)")


def parse_amount(value: str) -> float:
    text = value.strip().replace("$", "").replace(",", "")
    negative = text.startswith("(") and text.endswith(")")
    try:
        amount = float(text.strip("()"))
    except ValueError:
        raise ValueError(f"unrecognized amount '{value}'") from None
    return -amount if negative else amount


@router.post("/import/balances")
def import_balances(body: BalanceImport, session: Session = Depends(get_session)):
    """Import balance history from CSV with columns date, account, balance[, kind, tax_treatment]."""
    reader = csv.DictReader(io.StringIO(body.csv.lstrip("\ufeff")))
    headers = {h.strip().lower(): h for h in reader.fieldnames or []}
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise HTTPException(400, f"CSV needs columns date, account, balance (missing: {', '.join(missing)})")

    accounts = {a.name.strip().lower(): a for a in session.scalars(select(Account))}
    imported, created, errors = 0, [], []
    for line, row in enumerate(reader, start=2):
        def cell(column: str) -> str:
            return (row.get(headers[column]) or "").strip() if column in headers else ""

        name = cell("account")
        try:
            if not name:
                raise ValueError("account name is empty")
            as_of = parse_date(cell("date"))
            balance = parse_amount(cell("balance"))
            acct = accounts.get(name.lower())
            if acct is None:
                if not body.create_missing:
                    raise ValueError(f"no account named '{name}'")
                kind = cell("kind").lower() or "other_asset"
                if kind not in ACCOUNT_KINDS:
                    raise ValueError(f"unknown kind '{kind}' (one of: {', '.join(ACCOUNT_KINDS)})")
                default_tax = "taxable" if kind in ("cash", "brokerage", "retirement") else "none"
                tax = cell("tax_treatment").lower() or default_tax
                if tax not in TAX_TREATMENTS:
                    raise ValueError(f"unknown tax_treatment '{tax}' (one of: {', '.join(TAX_TREATMENTS)})")
                acct = Account(name=name, kind=kind, tax_treatment=tax)
                session.add(acct)
                session.flush()
                accounts[name.lower()] = acct
                created.append(name)
            upsert_balance(session, acct, balance, as_of)
            session.flush()
            imported += 1
        except ValueError as err:
            errors.append({"line": line, "message": str(err)})
    session.commit()
    return {"imported": imported, "created_accounts": created, "errors": errors}


@router.get("/export/balances.csv")
def export_balances(session: Session = Depends(get_session)):
    rows = session.execute(
        select(BalanceSnapshot, Account)
        .join(Account, BalanceSnapshot.account_id == Account.id)
        .order_by(BalanceSnapshot.as_of, Account.name)
    ).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["date", "account", "kind", "tax_treatment", "balance"])
    for snap, acct in rows:
        writer.writerow([snap.as_of.isoformat(), acct.name, acct.kind, acct.tax_treatment, f"{snap.balance:.2f}"])
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="balances-{date.today().isoformat()}.csv"'},
    )


BACKUP_FORMAT = "personal-finance-tool-backup"
BACKUP_VERSION = 1


class BackupBalance(BaseModel):
    as_of: date
    balance: float


class BackupHolding(BaseModel):
    symbol: str | None = None
    name: str
    asset_class: str = "other"
    quantity: float = 0.0
    value: float = 0.0
    as_of: date


class BackupAccount(AccountBase):
    archived: bool = False
    plaid_account_id: str | None = None
    plaid_item_id: str | None = None  # Plaid's item id, not a database id
    balances: list[BackupBalance] = []
    holdings: list[BackupHolding] = []


class BackupPlan(PlanCreate):
    cash_flows: list[CashFlowCreate] = []
    children: list[ChildCreate] = []


class Backup(BaseModel):
    format: str
    version: int
    exported_at: datetime | None = None
    accounts: list[BackupAccount] = []
    plans: list[BackupPlan] = []


class RestoreRequest(BaseModel):
    backup: Backup
    replace: bool = False


@router.get("/backup")
def export_backup(session: Session = Depends(get_session)):
    """Everything except Plaid access tokens, as JSON. Re-link institutions after restoring elsewhere."""
    accounts = []
    for acct in session.scalars(select(Account).order_by(Account.id)):
        item = acct.plaid_item
        accounts.append(
            BackupAccount(
                **AccountBase.model_validate(acct, from_attributes=True).model_dump(),
                archived=acct.archived,
                plaid_account_id=acct.plaid_account_id,
                plaid_item_id=item.item_id if item else None,
                balances=[BackupBalance(as_of=b.as_of, balance=b.balance) for b in acct.balances],
                holdings=[BackupHolding.model_validate(h, from_attributes=True) for h in acct.holdings],
            ).model_dump(mode="json")
        )
    plans = [
        BackupPlan.model_validate(plan, from_attributes=True).model_dump(mode="json")
        for plan in session.scalars(select(Plan).order_by(Plan.created_at))
    ]
    stamp = datetime.now().replace(microsecond=0)
    body = Backup(format=BACKUP_FORMAT, version=BACKUP_VERSION, exported_at=stamp).model_dump(mode="json")
    body.update(accounts=accounts, plans=plans)
    return Response(
        json.dumps(body, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="finance-backup-{stamp.date().isoformat()}.json"'},
    )


@router.post("/restore")
def restore_backup(body: RestoreRequest, session: Session = Depends(get_session)):
    """Replace all accounts and plans with a backup. Plaid links on this machine are kept."""
    backup = body.backup
    if backup.format != BACKUP_FORMAT:
        raise HTTPException(400, "This file is not a Personal Finance Tool backup.")
    if backup.version > BACKUP_VERSION:
        raise HTTPException(400, "This backup is from a newer version of the app; update the app first.")
    if not body.replace:
        raise HTTPException(400, "Restoring replaces all accounts and plans; confirm with replace=true.")

    for model in (Account, Plan):
        for obj in session.scalars(select(model)):
            session.delete(obj)
    session.flush()

    items = {i.item_id: i for i in session.scalars(select(PlaidItem))}
    for a in backup.accounts:
        fields = a.model_dump(exclude={"balances", "holdings", "plaid_item_id"})
        acct = Account(**fields, plaid_item=items.get(a.plaid_item_id))
        acct.balances = [BalanceSnapshot(as_of=b.as_of, balance=b.balance) for b in a.balances]
        acct.holdings = [Holding(**h.model_dump()) for h in a.holdings]
        session.add(acct)
    for p in backup.plans:
        plan = Plan(**p.model_dump(exclude={"cash_flows", "children"}))
        plan.cash_flows = [CashFlow(**cf.model_dump()) for cf in p.cash_flows]
        plan.children = [Child(**c.model_dump()) for c in p.children]
        session.add(plan)
    session.commit()
    return {"accounts": len(backup.accounts), "plans": len(backup.plans)}

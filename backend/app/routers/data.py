import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ACCOUNT_KINDS, Account, BalanceSnapshot
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

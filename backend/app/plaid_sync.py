"""Map Plaid accounts, holdings, and liabilities onto local accounts and balance snapshots."""

from datetime import date, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, BalanceSnapshot, Holding, PlaidItem

TAX_FREE_SUBTYPES = {"roth", "roth 401k", "roth 403b", "tfsa", "hsa", "529", "cash isa", "isa"}
TAX_DEFERRED_SUBTYPES = {
    "401a", "401k", "403b", "457b", "ira", "sep ira", "simple ira", "keogh", "pension",
    "thrift savings plan", "rrsp", "retirement", "profit sharing plan", "rrif", "lira", "sipp",
}
SECURITY_ASSET_CLASS = {
    "equity": "stocks",
    "etf": "funds",
    "mutual fund": "funds",
    "fixed income": "bonds",
    "cash": "cash",
    "cryptocurrency": "crypto",
}


class Gateway(Protocol):
    def get_accounts(self, access_token: str) -> list[dict]: ...
    def get_holdings(self, access_token: str) -> dict | None: ...
    def get_liabilities(self, access_token: str) -> dict | None: ...


def classify(plaid_type: str | None, subtype: str | None) -> tuple[str, str]:
    """Return (kind, tax_treatment) for a Plaid account type/subtype."""
    plaid_type = (plaid_type or "").lower()
    subtype = (subtype or "").lower()
    if plaid_type == "depository":
        return "cash", "taxable"
    if plaid_type == "investment":
        if subtype in TAX_FREE_SUBTYPES:
            return "retirement", "tax_free"
        if subtype in TAX_DEFERRED_SUBTYPES:
            return "retirement", "tax_deferred"
        return "brokerage", "taxable"
    if plaid_type == "credit":
        return "credit_card", "none"
    if plaid_type == "loan":
        return ("mortgage" if subtype == "mortgage" else "loan"), "none"
    return "other_asset", "none"


def _record_balance(session: Session, account: Account, balance: float, as_of: date) -> None:
    snap = session.scalar(
        select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id, BalanceSnapshot.as_of == as_of)
    )
    if snap:
        snap.balance = balance
    else:
        session.add(BalanceSnapshot(account_id=account.id, as_of=as_of, balance=balance))


def _apply_liabilities(by_plaid_id: dict[str, Account], liabilities: dict) -> None:
    for credit in liabilities.get("credit") or []:
        acct = by_plaid_id.get(credit.get("account_id"))
        if not acct:
            continue
        aprs = [a for a in credit.get("aprs") or [] if a.get("apr_type") == "purchase_apr"] or credit.get("aprs") or []
        if aprs and not acct.interest_rate:
            acct.interest_rate = (aprs[0].get("apr_percentage") or 0) / 100
        if credit.get("minimum_payment_amount") and not acct.monthly_payment:
            acct.monthly_payment = credit["minimum_payment_amount"]
    for mortgage in liabilities.get("mortgage") or []:
        acct = by_plaid_id.get(mortgage.get("account_id"))
        if not acct:
            continue
        rate = (mortgage.get("interest_rate") or {}).get("percentage")
        if rate and not acct.interest_rate:
            acct.interest_rate = rate / 100
        if mortgage.get("next_monthly_payment") and not acct.monthly_payment:
            acct.monthly_payment = mortgage["next_monthly_payment"]
    for student in liabilities.get("student") or []:
        acct = by_plaid_id.get(student.get("account_id"))
        if not acct:
            continue
        if student.get("interest_rate_percentage") and not acct.interest_rate:
            acct.interest_rate = student["interest_rate_percentage"] / 100
        if student.get("minimum_payment_amount") and not acct.monthly_payment:
            acct.monthly_payment = student["minimum_payment_amount"]


def sync_item(session: Session, item: PlaidItem, gateway: Gateway, today: date | None = None) -> dict:
    today = today or date.today()
    by_plaid_id: dict[str, Account] = {}
    created = updated = 0

    for pa in gateway.get_accounts(item.access_token):
        acct = session.scalar(select(Account).where(Account.plaid_account_id == pa["account_id"]))
        if acct is None:
            kind, tax = classify(pa.get("type"), pa.get("subtype"))
            name = pa.get("name") or pa.get("official_name") or "Linked account"
            if pa.get("mask"):
                name = f"{name} ••{pa['mask']}"
            acct = Account(
                name=name,
                institution=item.institution_name,
                kind=kind,
                tax_treatment=tax,
                plaid_account_id=pa["account_id"],
                plaid_item_id=item.id,
            )
            session.add(acct)
            session.flush()
            created += 1
        else:
            updated += 1
        by_plaid_id[pa["account_id"]] = acct
        current = (pa.get("balances") or {}).get("current")
        if current is not None:
            _record_balance(session, acct, abs(current) if acct.is_liability else current, today)

    holdings_count = 0
    holdings = gateway.get_holdings(item.access_token)
    if holdings:
        securities = {s["security_id"]: s for s in holdings.get("securities") or []}
        for acct in by_plaid_id.values():
            acct.holdings.clear()
        for h in holdings.get("holdings") or []:
            acct = by_plaid_id.get(h.get("account_id"))
            if not acct:
                continue
            sec = securities.get(h.get("security_id"), {})
            acct.holdings.append(
                Holding(
                    symbol=sec.get("ticker_symbol"),
                    name=sec.get("name") or sec.get("ticker_symbol") or "Unknown security",
                    asset_class=SECURITY_ASSET_CLASS.get((sec.get("type") or "").lower(), "other"),
                    quantity=h.get("quantity") or 0.0,
                    value=h.get("institution_value") or 0.0,
                    as_of=today,
                )
            )
            holdings_count += 1

    liabilities = gateway.get_liabilities(item.access_token)
    if liabilities:
        _apply_liabilities(by_plaid_id, liabilities)

    item.last_synced_at = datetime.now()
    session.commit()
    return {"accounts_created": created, "accounts_updated": updated, "holdings": holdings_count}

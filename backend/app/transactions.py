"""Categorize bank transactions and compare actual spending with a plan."""

import csv
import hashlib
import io
import re
from collections import defaultdict
from datetime import date
from typing import get_args

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, CategoryRule, Transaction
from .routers.data import parse_amount, parse_date
from .schemas import ExpenseCategory

SPENDING_CATEGORIES = tuple(c for c in get_args(ExpenseCategory) if c != "general")
# Money that moves but is not spending in the plan's sense: the plan models income, debt payments,
# and taxes separately, and transfers between your own accounts are not spending at all.
EXCLUDED_CATEGORIES = ("income", "transfer", "debt_payment", "taxes", "ignore")
CATEGORIES = SPENDING_CATEGORIES + EXCLUDED_CATEGORIES

PLAID_PRIMARY = {
    "INCOME": "income",
    "TRANSFER_IN": "transfer",
    "TRANSFER_OUT": "transfer",
    "LOAN_PAYMENTS": "debt_payment",
    "LOAN_DISBURSEMENTS": "transfer",
    "BANK_FEES": "other",
    "ENTERTAINMENT": "hobbies",
    "FOOD_AND_DRINK": "food",
    "GENERAL_MERCHANDISE": "other",
    "HOME_IMPROVEMENT": "home_maintenance",
    "MEDICAL": "healthcare",
    "PERSONAL_CARE": "other",
    "GENERAL_SERVICES": "other",
    "GOVERNMENT_AND_NON_PROFIT": "other",
    "TRANSPORTATION": "transportation",
    "TRAVEL": "travel",
    "RENT_AND_UTILITIES": "utilities",
}
PLAID_DETAILED = {
    "RENT_AND_UTILITIES_RENT": "housing",
    "GENERAL_SERVICES_INSURANCE": "insurance",
    "GENERAL_SERVICES_EDUCATION": "education",
    "GENERAL_SERVICES_CHILDCARE": "kids",
    "GENERAL_SERVICES_AUTOMOTIVE": "transportation",
    "GOVERNMENT_AND_NON_PROFIT_DONATIONS": "giving",
    "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT": "taxes",
    "GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES": "other",
}
# For CSV rows: matched against the file's category column first, then the description.
KEYWORDS = (
    ("transfer", ("transfer", "zelle to", "venmo cashout", "brokerage", "investment")),
    ("debt_payment", ("credit card payment", "autopay", "mortgage", "loan payment", "student loan")),
    ("income", ("payroll", "direct deposit", "salary", "paycheck", "interest paid", "dividend")),
    ("taxes", ("irs", "tax payment", "franchise tax")),
    ("food", ("grocer", "supermarket", "restaurant", "dining", "food", "cafe", "coffee", "starbucks",
              "whole foods", "trader joe", "safeway", "kroger", "costco", "doordash", "uber eats", "grubhub")),
    ("transportation", ("gas station", "fuel", "shell", "chevron", "exxon", "uber", "lyft", "parking", "toll",
                        "auto", "car wash", "transit")),
    ("utilities", ("utilit", "electric", "water", "internet", "comcast", "verizon", "at&t", "t-mobile", "phone")),
    ("housing", ("rent", "hoa", "property tax")),
    ("home_maintenance", ("home depot", "lowe's", "lowes", "hardware", "plumb", "repair")),
    ("healthcare", ("pharmacy", "cvs", "walgreens", "doctor", "medical", "dental", "health", "hospital")),
    ("insurance", ("insurance", "geico", "allstate", "progressive", "state farm")),
    ("travel", ("airline", "hotel", "airbnb", "travel", "flight", "delta", "united", "southwest", "expedia")),
    ("hobbies", ("entertainment", "netflix", "spotify", "hulu", "cinema", "theater", "gym", "steam", "hobby")),
    ("kids", ("childcare", "daycare", "toys")),
    ("education", ("tuition", "school", "university", "college")),
    ("giving", ("donation", "charity", "church")),
)


def merchant_key(merchant: str | None, description: str) -> str:
    """Normalize a merchant or description so rules match despite store numbers and reference codes."""
    text = (merchant or description).lower()
    text = re.sub(r"[#*]\S*|\d+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def categorize_plaid(pfc: dict | None) -> str:
    if not pfc:
        return "other"
    return PLAID_DETAILED.get(pfc.get("detailed") or "") or PLAID_PRIMARY.get(pfc.get("primary") or "", "other")


def guess_category(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        lowered = text.strip().lower()
        if lowered in CATEGORIES:
            return lowered
        for category, words in KEYWORDS:
            if any(re.search(rf"\b{re.escape(w)}", lowered) for w in words):
                return category
    return None


def load_rules(session: Session) -> dict[str, str]:
    return {r.match: r.category for r in session.scalars(select(CategoryRule))}


def _apply_rule(txn: Transaction, rules: dict[str, str]) -> None:
    if txn.category_source == "user":
        return
    rule = rules.get(merchant_key(txn.merchant, txn.description))
    if rule:
        txn.category, txn.category_source = rule, "rule"


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def apply_plaid_transactions(session: Session, by_plaid_id: dict[str, Account], data: dict) -> int:
    """Apply one /transactions/sync result. User-chosen categories survive Plaid's updates."""
    rules = load_rules(session)
    updates = (data.get("added") or []) + (data.get("modified") or [])
    ids = [t["transaction_id"] for t in updates]
    existing = {t.external_id: t for t in session.scalars(select(Transaction).where(Transaction.external_id.in_(ids)))}
    changed = 0
    for t in updates:
        acct = by_plaid_id.get(t.get("account_id"))
        if acct is None:
            continue
        txn = existing.get(t["transaction_id"])
        if txn is None:
            txn = existing[t["transaction_id"]] = Transaction(external_id=t["transaction_id"], category_source="auto")
            session.add(txn)
        pfc = t.get("personal_finance_category") or {}
        txn.account_id = acct.id
        txn.posted_on = _as_date(t.get("authorized_date") or t["date"])
        txn.description = t.get("name") or t.get("merchant_name") or "Transaction"
        txn.merchant = t.get("merchant_name")
        txn.amount = float(t.get("amount") or 0)
        txn.pending = bool(t.get("pending"))
        txn.plaid_category = pfc.get("detailed") or pfc.get("primary")
        if txn.category_source == "auto":
            txn.category = categorize_plaid(pfc)
        _apply_rule(txn, rules)
        changed += 1
    removed = [r.get("transaction_id") for r in data.get("removed") or []]
    if removed:
        for txn in session.scalars(select(Transaction).where(Transaction.external_id.in_(removed))):
            session.delete(txn)
    return changed


DESCRIPTION_COLUMNS = ("description", "name", "payee", "merchant", "memo")


def import_csv(session: Session, text: str, negative_is_spending: bool = True) -> dict:
    """Import transactions from CSV with columns date, description, amount[, account, category].

    Bank exports usually show purchases as negative amounts; set negative_is_spending=False for
    files where purchases are positive. Rows already imported are skipped.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    headers = {h.strip().lower(): h for h in reader.fieldnames or []}
    desc_col = next((headers[c] for c in DESCRIPTION_COLUMNS if c in headers), None)
    missing = [c for c in ("date", "amount") if c not in headers] + ([] if desc_col else ["description"])
    if missing:
        raise ValueError(f"CSV needs columns date, description, amount (missing: {', '.join(missing)})")

    accounts = {a.name.strip().lower(): a for a in session.scalars(select(Account))}
    rules = load_rules(session)
    existing = set(session.scalars(select(Transaction.external_id).where(Transaction.external_id.like("csv:%"))))
    imported = duplicates = 0
    errors: list[dict] = []
    seen: dict[str, int] = defaultdict(int)
    for line, row in enumerate(reader, start=2):
        def cell(column: str, row: dict = row) -> str:
            return (row.get(headers.get(column, ""), "") or "").strip()

        try:
            posted = parse_date(cell("date"))
            amount = parse_amount(cell("amount"))
        except ValueError as err:
            errors.append({"line": line, "message": str(err)})
            continue
        description = (row.get(desc_col) or "").strip() or "Transaction"
        account_name = cell("account")
        acct = accounts.get(account_name.lower()) if account_name else None
        if account_name and acct is None:
            errors.append({"line": line, "message": f"no account named '{account_name}'"})
            continue
        if negative_is_spending:
            amount = -amount
        # Identical rows in one file are distinct purchases, so number them.
        base = f"{posted}|{description}|{amount:.2f}|{acct.id if acct else ''}"
        seen[base] += 1
        external_id = "csv:" + hashlib.sha1(f"{base}|{seen[base]}".encode()).hexdigest()[:20]
        if external_id in existing:
            duplicates += 1
            continue
        existing.add(external_id)
        category = guess_category(cell("category"), description)
        if category is None:
            category = "income" if amount < 0 else "other"
        txn = Transaction(
            account_id=acct.id if acct else None, external_id=external_id, posted_on=posted,
            description=description, amount=amount, category=category, category_source="auto",
        )
        _apply_rule(txn, rules)
        session.add(txn)
        imported += 1
    session.commit()
    return {"imported": imported, "duplicates": duplicates, "errors": errors}


def set_category(session: Session, txn: Transaction, category: str, remember: bool) -> int:
    """Set one transaction's category; with remember, also every other one from that merchant."""
    txn.category, txn.category_source = category, "user"
    updated = 1
    if remember:
        key = merchant_key(txn.merchant, txn.description)
        rule = session.scalar(select(CategoryRule).where(CategoryRule.match == key))
        if rule is None:
            session.add(CategoryRule(match=key, category=category))
        else:
            rule.category = category
        for other in session.scalars(select(Transaction).where(Transaction.id != txn.id)):
            if other.category_source != "user" and merchant_key(other.merchant, other.description) == key:
                other.category, other.category_source = category, "rule"
                updated += 1
    session.commit()
    return updated


def _month_start(d: date, offset: int = 0) -> date:
    index = d.year * 12 + d.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def spending_summary(
    session: Session, months: int, today: date | None = None, planned: dict[str, float] | None = None
) -> dict:
    """Average spending by category over the last complete months, annualized, beside the plan.

    Uses only months that have transactions, so a recently linked account is not averaged
    over months before its history begins. With no complete month yet, uses this month so far.
    """
    today = today or date.today()
    end = _month_start(today)
    start = _month_start(today, -months)
    query = select(Transaction).where(Transaction.pending.is_(False))
    txns = list(session.scalars(query.where(Transaction.posted_on >= start, Transaction.posted_on < end)))
    partial = False
    if txns:
        first = min(t.posted_on for t in txns)
        start = _month_start(first)
        covered = (end.year - start.year) * 12 + end.month - start.month
    else:
        txns = list(session.scalars(query.where(Transaction.posted_on >= end, Transaction.posted_on <= today)))
        start, partial = end, bool(txns)
        next_month = _month_start(today, 1)
        covered = today.day / (next_month - end).days

    by_category: dict[str, float] = defaultdict(float)
    by_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    merchants: dict[str, list] = {}
    for t in txns:
        by_category[t.category] += t.amount
        if t.category in SPENDING_CATEGORIES:
            by_month[t.posted_on.strftime("%Y-%m")][t.category] += t.amount
            name = t.merchant or t.description
            entry = merchants.setdefault(merchant_key(t.merchant, t.description), [name, 0.0, 0])
            entry[1] += t.amount
            entry[2] += 1

    annualize = 12 / covered if covered else 0.0
    planned = planned or {}
    categories = []
    for c in SPENDING_CATEGORIES + ("general",):
        actual = by_category.get(c, 0.0) * annualize
        plan = planned.get(c, 0.0)
        if actual or plan:
            categories.append({"category": c, "actual_annual": actual, "planned_annual": plan if planned else None})
    month_keys = []
    cursor = start
    while cursor < (end if not partial else _month_start(today, 1)):
        month_keys.append(cursor.strftime("%Y-%m"))
        cursor = _month_start(cursor, 1)
    top = sorted(merchants.values(), key=lambda m: -m[1])[:8]
    return {
        "start": start.isoformat(),
        "end": (today if partial else date.fromordinal(end.toordinal() - 1)).isoformat(),
        "months": covered,
        "partial": partial,
        "transaction_count": len(txns),
        "categories": categories,
        "actual_annual": sum(c["actual_annual"] for c in categories),
        "planned_annual": sum(planned.values()) if planned else None,
        "excluded": {c: by_category[c] for c in EXCLUDED_CATEGORIES if by_category.get(c)},
        "monthly": [{"month": m, "by_category": dict(by_month.get(m, {}))} for m in month_keys],
        "top_merchants": [{"name": n, "total": total, "count": count} for n, total, count in top],
    }

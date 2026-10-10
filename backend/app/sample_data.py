"""A made-up household for trying the app before entering real numbers, as backup contents.

Dates are relative to `today` so the history always ends now and the people keep their ages.
"""

import random
from datetime import date, timedelta

BALANCE_QUARTERS = 12
TRANSACTION_MONTHS = 6


def _months_ago(today: date, months: int) -> date:
    y, m = divmod(today.year * 12 + today.month - 1 - months, 12)
    return date(y, m + 1, 1)


def _history(today: date, current: float, yearly_growth: float, rng: random.Random) -> list[dict]:
    """Quarterly balances ending at `current`, growing about `yearly_growth` a year with some noise."""
    out = []
    for q in range(BALANCE_QUARTERS, 0, -1):
        wobble = 1 + rng.uniform(-0.03, 0.03) if yearly_growth else 1
        value = current / (1 + yearly_growth) ** (q / 4) * wobble
        out.append({"as_of": _months_ago(today, q * 3).isoformat(), "balance": round(value, 2)})
    out.append({"as_of": today.isoformat(), "balance": current})
    return out


def _debt_history(today: date, current: float, yearly_paydown: float) -> list[dict]:
    out = [
        {"as_of": _months_ago(today, q * 3).isoformat(), "balance": round(current + yearly_paydown * q / 4, 2)}
        for q in range(BALANCE_QUARTERS, 0, -1)
    ]
    out.append({"as_of": today.isoformat(), "balance": current})
    return out


def _account(id_: int, name: str, kind: str, tax: str, balances: list[dict], **extra) -> dict:
    return {"id": id_, "name": name, "institution": "Sample Bank", "kind": kind, "tax_treatment": tax,
            "balances": balances, **extra}


MONTHLY_SPENDING = (
    # description, category, typical amount, times per month
    ("KING SOOPERS #112", "food", 145.0, 6),
    ("TRADER JOE'S", "food", 88.0, 3),
    ("CHIPOTLE ONLINE", "food", 34.0, 3),
    ("XCEL ENERGY", "utilities", 165.0, 1),
    ("DENVER WATER", "utilities", 72.0, 1),
    ("COMCAST INTERNET", "utilities", 80.0, 1),
    ("SHELL OIL", "transportation", 52.0, 4),
    ("GEICO AUTO", "insurance", 186.0, 1),
    ("KING SOOPERS PHARMACY", "healthcare", 28.0, 1),
    ("NETFLIX.COM", "hobbies", 15.49, 1),
    ("REI #45", "hobbies", 95.0, 1),
    ("BRIGHT HORIZONS", "kids", 1450.0, 1),
    ("HOME DEPOT", "home_maintenance", 120.0, 1),
    ("AMAZON.COM", "other", 85.0, 9),
    ("TARGET #1534", "other", 70.0, 3),
    ("UNITED AIRLINES", "travel", 520.0, 1),
    ("AIRBNB", "travel", 230.0, 1),
)


def _transactions(today: date, checking_id: int, card_id: int, rng: random.Random) -> list[dict]:
    out = []
    for m in range(TRANSACTION_MONTHS, 0, -1):
        start = _months_ago(today, m)
        days = (_months_ago(today, m - 1) - start).days
        for description, category, amount, times in MONTHLY_SPENDING:
            for _ in range(times):
                posted = start + timedelta(days=rng.randrange(days))
                out.append({
                    "account_id": card_id, "posted_on": posted.isoformat(), "description": description,
                    "amount": round(amount * rng.uniform(0.8, 1.2), 2), "category": category,
                })
        for posted_day, description, amount, category in (
            (1, "MORTGAGE PMT ROCKET", 2150.0, "debt_payment"),
            (15, "PAYROLL DEPOSIT ACME", -8600.0, "income"),
            (28, "CARD PAYMENT THANK YOU", 3400.0, "transfer"),
        ):
            out.append({
                "account_id": checking_id, "posted_on": (start + timedelta(days=posted_day - 1)).isoformat(),
                "description": description, "amount": amount, "category": category,
            })
    out.sort(key=lambda t: t["posted_on"])
    return out


def sample_backup(today: date | None = None) -> dict:
    today = today or date.today()
    rng = random.Random(7)
    you, spouse = today.year - 39, today.year - 37
    accounts = [
        _account(1, "Everyday checking", "cash", "taxable", _history(today, 18_500, 0.0, rng)),
        _account(2, "High-yield savings", "cash", "taxable", _history(today, 42_000, 0.08, rng)),
        _account(3, "Joint brokerage", "brokerage", "taxable", _history(today, 128_000, 0.14, rng),
                 cost_basis=96_000, annual_contribution=6_000),
        _account(4, "Your 401(k)", "retirement", "tax_deferred", _history(today, 312_000, 0.16, rng),
                 annual_contribution=23_000),
        _account(5, "Spouse's 401(k)", "retirement", "tax_deferred", _history(today, 176_000, 0.17, rng),
                 annual_contribution=15_000, owner="spouse"),
        _account(6, "Roth IRA", "retirement", "tax_free", _history(today, 64_000, 0.15, rng),
                 annual_contribution=7_000),
        _account(7, "House", "property", "none", _history(today, 525_000, 0.04, rng)),
        _account(8, "Mortgage", "mortgage", "none", _debt_history(today, 338_000, 8_400),
                 interest_rate=0.031, monthly_payment=2_150),
        _account(9, "Car loan", "loan", "none", _debt_history(today, 13_800, 5_100),
                 interest_rate=0.049, monthly_payment=455),
        _account(10, "Rewards credit card", "credit_card", "none", _history(today, 2_350, 0.0, rng),
                 interest_rate=0.229),
    ]
    flow = {"start_age": None, "end_age": None, "ends_at_retirement": False, "starts_at_retirement": False,
            "real_growth": 0.0, "tax_type": "wages", "category": "general", "every_n_years": 1, "owner": "joint"}
    cash_flows = [
        {**flow, "name": "Your salary", "kind": "income", "amount": 145_000, "ends_at_retirement": True,
         "real_growth": 0.01, "owner": "self"},
        {**flow, "name": "Spouse's salary", "kind": "income", "amount": 98_000, "ends_at_retirement": True,
         "real_growth": 0.01, "owner": "spouse"},
        {**flow, "name": "Groceries & dining", "kind": "expense", "amount": 17_000, "category": "food"},
        {**flow, "name": "Utilities & internet", "kind": "expense", "amount": 6_000, "category": "utilities"},
        {**flow, "name": "Gas & car upkeep", "kind": "expense", "amount": 4_500, "category": "transportation"},
        {**flow, "name": "Replace a car", "kind": "expense", "amount": 38_000, "category": "transportation",
         "start_age": 42, "every_n_years": 8},
        {**flow, "name": "Insurance", "kind": "expense", "amount": 4_800, "category": "insurance"},
        {**flow, "name": "Travel", "kind": "expense", "amount": 9_000, "category": "travel"},
        {**flow, "name": "Hobbies & fun", "kind": "expense", "amount": 6_000, "category": "hobbies"},
        {**flow, "name": "Everything else", "kind": "expense", "amount": 12_000, "category": "other"},
        {**flow, "name": "Kitchen remodel", "kind": "goal", "amount": 45_000, "start_age": 45},
    ]
    plan = {
        "name": "Sample: Alex & Sam", "birth_year": you, "retirement_age": 55, "life_expectancy": 92,
        "spouse_birth_year": spouse, "spouse_retirement_age": 55, "spouse_life_expectancy": 95,
        "filing_status": "married_joint", "state": "CO",
        "ss_monthly_benefit": 3_150, "ss_claim_age": 67, "spouse_ss_monthly_benefit": 2_300, "spouse_ss_claim_age": 67,
        "cash_flows": cash_flows,
        "children": [
            {"name": "Maya", "birth_year": today.year - 7, "college_cost": 32_000},
            {"name": "Leo", "birth_year": today.year - 4, "college_cost": 32_000},
        ],
        "homes": [{
            "name": "House", "value": 525_000, "cost_basis": 410_000, "property_account_id": 7,
            "mortgage_account_id": 8, "mortgage_balance": 338_000, "mortgage_payment": 2_150,
            "mortgage_rate": 0.031, "appreciation": 0.005, "carrying_costs": 0.015,
        }],
    }
    return {
        "accounts": accounts,
        "plans": [plan],
        "transactions": _transactions(today, checking_id=1, card_id=10, rng=rng),
        "category_rules": [],
    }

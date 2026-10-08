from datetime import date

import pytest
from test_plaid_sync import FakeGateway

from app.models import PlaidItem, Transaction
from app.plaid_sync import sync_item
from app.transactions import categorize_plaid, import_csv, merchant_key, set_category, spending_summary

TODAY = date(2026, 10, 7)


def _txn(tid, amount, primary, detailed=None, day="2026-09-03", **extra):
    return {"transaction_id": tid, "account_id": "chk", "amount": amount, "date": day, "name": f"Payee {tid}",
            "personal_finance_category": {"primary": primary, "detailed": detailed or primary}, **extra}


class TxnGateway(FakeGateway):
    def __init__(self, pages):
        super().__init__()
        self.pages = pages
        self.cursors = []

    def sync_transactions(self, access_token, cursor):
        self.cursors.append(cursor)
        return self.pages.pop(0) if self.pages else {"added": [], "modified": [], "removed": [], "next_cursor": cursor}


@pytest.mark.parametrize(
    "pfc, expected",
    [
        ({"primary": "FOOD_AND_DRINK", "detailed": "FOOD_AND_DRINK_GROCERIES"}, "food"),
        ({"primary": "RENT_AND_UTILITIES", "detailed": "RENT_AND_UTILITIES_RENT"}, "housing"),
        ({"primary": "RENT_AND_UTILITIES", "detailed": "RENT_AND_UTILITIES_GAS_AND_ELECTRICITY"}, "utilities"),
        ({"primary": "LOAN_PAYMENTS", "detailed": "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"}, "debt_payment"),
        ({"primary": "TRANSFER_OUT", "detailed": "TRANSFER_OUT_ACCOUNT_TRANSFER"}, "transfer"),
        ({"primary": "GOVERNMENT_AND_NON_PROFIT", "detailed": "GOVERNMENT_AND_NON_PROFIT_DONATIONS"}, "giving"),
        ({"primary": "SOMETHING_NEW"}, "other"),
        (None, "other"),
    ],
)
def test_categorize_plaid(pfc, expected):
    assert categorize_plaid(pfc) == expected


def test_merchant_key_ignores_store_numbers():
    assert merchant_key(None, "SAFEWAY #1234 SAN JOSE") == merchant_key(None, "Safeway #988 san jose")
    assert merchant_key("Amazon", "AMZN MKTP US*2K4") == "amazon"


def test_plaid_sync_adds_updates_and_removes(session_factory):
    pages = [
        {"added": [_txn("t1", 120.0, "FOOD_AND_DRINK"), _txn("t2", 1500.0, "LOAN_PAYMENTS"),
                   _txn("t3", 40.0, "ENTERTAINMENT", pending=True)],
         "modified": [], "removed": [], "next_cursor": "c1"},
        {"added": [], "modified": [_txn("t1", 125.0, "FOOD_AND_DRINK")], "removed": [{"transaction_id": "t2"}],
         "next_cursor": "c2"},
    ]
    gateway = TxnGateway(pages)
    with session_factory() as session:
        item = PlaidItem(item_id="item-1", access_token="tok")
        session.add(item)
        session.commit()

        assert sync_item(session, item, gateway)["transactions"] == 3
        txns = {t.external_id: t for t in session.query(Transaction)}
        assert txns["t1"].category == "food" and txns["t2"].category == "debt_payment" and txns["t3"].pending
        assert item.transactions_cursor == "c1"

        set_category(session, txns["t1"], "hobbies", remember=False)
        sync_item(session, item, gateway)
        assert gateway.cursors == [None, "c1"]
        session.expire_all()
        txns = {t.external_id: t for t in session.query(Transaction)}
        assert set(txns) == {"t1", "t3"}
        assert txns["t1"].amount == 125.0 and txns["t1"].category == "hobbies"  # your choice survives updates
        assert item.transactions_cursor == "c2"


CSV = """Date,Description,Amount,Category
09/02/2026,WHOLE FOODS #123,-84.20,
09/02/2026,WHOLE FOODS #123,-84.20,
09/05/2026,ACME PAYROLL,3000.00,
09/09/2026,Mystery Shop,-25.00,Travel
09/12/2026,Corner Bistro,-40.00,
"""


def test_csv_import_signs_categories_and_duplicates(session_factory):
    with session_factory() as session:
        result = import_csv(session, CSV)
        assert result == {"imported": 5, "duplicates": 0, "errors": []}
        txns = session.query(Transaction).order_by(Transaction.id).all()
        assert [t.amount for t in txns] == [84.20, 84.20, -3000.0, 25.0, 40.0]
        assert [t.category for t in txns] == ["food", "food", "income", "travel", "other"]

        assert import_csv(session, CSV) == {"imported": 0, "duplicates": 5, "errors": []}

        bad = import_csv(session, "date,description,amount,account\nnope,x,1,\n09/01/2026,y,1,Nowhere\n")
        assert [e["line"] for e in bad["errors"]] == [2, 3]

        with pytest.raises(ValueError, match="amount"):
            import_csv(session, "date,description\n09/01/2026,x\n")


def test_remembered_category_applies_to_merchant_now_and_later(session_factory):
    with session_factory() as session:
        import_csv(session, "date,description,amount\n09/01/2026,CORNER BISTRO 01,-30\n09/08/2026,Corner Bistro 02,-20")
        first = session.query(Transaction).order_by(Transaction.id).first()
        assert set_category(session, first, "food", remember=True) == 2
        import_csv(session, "date,description,amount\n09/15/2026,Corner Bistro 03,-10\n")
        assert {t.category for t in session.query(Transaction)} == {"food"}
        assert {t.category_source for t in session.query(Transaction)} == {"user", "rule"}


def test_summary_annualizes_months_with_data(session_factory):
    with session_factory() as session:
        import_csv(session, "\n".join([
            "date,description,amount,category",
            "08/03/2026,Groceries,-500,food",
            "09/03/2026,Groceries,-700,food",
            "09/10/2026,Rent,-2000,housing",
            "09/11/2026,To savings,-1000,transfer",
            "10/02/2026,Groceries,-999,food",  # current month: incomplete, left out
            "07/01/2025,Old,-5000,food",  # before the 12-month window
        ]))
        s = spending_summary(session, 12, today=TODAY, planned={"food": 6000, "housing": 30000, "travel": 2000})
        assert s["months"] == 2 and not s["partial"]
        assert s["start"] == "2026-08-01" and s["end"] == "2026-09-30"
        cats = {c["category"]: c for c in s["categories"]}
        assert cats["food"]["actual_annual"] == pytest.approx(1200 * 6)
        assert cats["housing"]["actual_annual"] == pytest.approx(2000 * 6)
        assert cats["travel"] == {"category": "travel", "actual_annual": 0.0, "planned_annual": 2000}
        assert s["actual_annual"] == pytest.approx(3200 * 6) and s["planned_annual"] == 38000
        assert s["excluded"] == {"transfer": 1000}
        assert [m["month"] for m in s["monthly"]] == ["2026-08", "2026-09"]
        assert s["top_merchants"][0]["name"] == "Rent"


def test_summary_uses_current_month_until_one_is_complete(session_factory):
    with session_factory() as session:
        import_csv(session, "date,description,amount,category\n10/02/2026,Groceries,-100,food\n")
        s = spending_summary(session, 12, today=TODAY)
        assert s["partial"] and s["months"] == pytest.approx(7 / 31)
        assert s["categories"][0]["actual_annual"] == pytest.approx(100 * 12 * 31 / 7)
        assert s["planned_annual"] is None


def test_spending_api_with_plan_and_backup(client):
    plan = client.post("/api/plans", json={"name": "P", "birth_year": 1980, "retirement_age": 60}).json()
    client.post(f"/api/plans/{plan['id']}/cash-flows",
                json={"name": "Food", "kind": "expense", "amount": 9000, "category": "food"})
    acct = client.post("/api/accounts", json={"name": "Checking", "kind": "cash", "balance": 5000}).json()
    csv_text = "date,description,amount,account\n" + "\n".join(
        f"{m:02d}/05/2026,Grocer,-600,Checking" for m in range(1, 10))
    assert client.post("/api/import/transactions", json={"csv": csv_text}).json()["imported"] == 9

    s = client.get(f"/api/spending/summary?plan_id={plan['id']}").json()
    food = next(c for c in s["categories"] if c["category"] == "food")
    assert food["planned_annual"] == pytest.approx(9000)
    assert food["actual_annual"] > 0

    txns = client.get("/api/transactions?category=food").json()
    assert len(txns) == 9 and txns[0]["account"] == "Checking" and txns[0]["source"] == "csv"
    r = client.patch(f"/api/transactions/{txns[0]['id']}", json={"category": "hobbies", "remember": True})
    assert r.json() == {"updated": 9}
    assert client.get("/api/spending/rules").json()[0]["category"] == "hobbies"
    assert client.patch(f"/api/transactions/{txns[0]['id']}", json={"category": "nope"}).status_code == 422

    backup = client.get("/api/backup").json()
    assert len(backup["transactions"]) == 9 and backup["transactions"][0]["account_id"] == acct["id"]
    client.delete("/api/transactions/imported")
    assert client.get("/api/transactions").json() == []
    restored = client.post("/api/restore", json={"backup": backup, "replace": True}).json()
    assert restored["transactions"] == 9
    after = client.get("/api/transactions").json()
    assert len(after) == 9 and after[0]["account"] == "Checking" and after[0]["category"] == "hobbies"
    assert len(client.get("/api/spending/rules").json()) == 1

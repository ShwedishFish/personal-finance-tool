from datetime import date

import pytest

from app.models import PlaidItem
from app.plaid_sync import classify, sync_item


class FakeGateway:
    def __init__(self, checking_balance=1_000.0):
        self.checking_balance = checking_balance

    def get_accounts(self, access_token):
        return [
            {"account_id": "chk", "name": "Checking", "mask": "0000", "type": "depository", "subtype": "checking",
             "balances": {"current": self.checking_balance}},
            {"account_id": "roth", "name": "Roth IRA", "type": "investment", "subtype": "roth",
             "balances": {"current": 50_000.0}},
            {"account_id": "cc", "name": "Visa", "type": "credit", "subtype": "credit card",
             "balances": {"current": 1_200.0}},
        ]

    def get_holdings(self, access_token):
        return {
            "securities": [{"security_id": "s1", "ticker_symbol": "VTI", "name": "Vanguard Total", "type": "etf"}],
            "holdings": [{"account_id": "roth", "security_id": "s1", "quantity": 100, "institution_value": 50_000}],
        }

    def get_liabilities(self, access_token):
        return {"credit": [{"account_id": "cc", "aprs": [{"apr_type": "purchase_apr", "apr_percentage": 22.0}],
                            "minimum_payment_amount": 35.0}]}

    def sync_transactions(self, access_token, cursor):
        return None


@pytest.mark.parametrize(
    "plaid_type, subtype, expected",
    [
        ("depository", "savings", ("cash", "taxable")),
        ("investment", "401k", ("retirement", "tax_deferred")),
        ("investment", "roth", ("retirement", "tax_free")),
        ("investment", "brokerage", ("brokerage", "taxable")),
        ("loan", "mortgage", ("mortgage", "none")),
        ("loan", "student", ("loan", "none")),
        ("credit", "credit card", ("credit_card", "none")),
    ],
)
def test_classify(plaid_type, subtype, expected):
    assert classify(plaid_type, subtype) == expected


def test_sync_creates_and_updates_accounts(session_factory):
    with session_factory() as session:
        item = PlaidItem(item_id="item-1", access_token="tok", institution_name="Test Bank")
        session.add(item)
        session.commit()

        result = sync_item(session, item, FakeGateway(), today=date(2026, 1, 1))
        assert result == {"accounts_created": 3, "accounts_updated": 0, "holdings": 1, "transactions": 0}
        accounts = {a.plaid_account_id: a for a in item.accounts}
        assert accounts["chk"].name == "Checking ••0000"
        assert accounts["roth"].tax_treatment == "tax_free"
        assert accounts["roth"].holdings[0].symbol == "VTI"
        assert accounts["cc"].is_liability and accounts["cc"].interest_rate == pytest.approx(0.22)
        assert accounts["cc"].monthly_payment == 35.0

        result = sync_item(session, item, FakeGateway(checking_balance=2_000.0), today=date(2026, 1, 1))
        assert result["accounts_created"] == 0 and result["accounts_updated"] == 3
        session.refresh(accounts["chk"])
        assert [b.balance for b in accounts["chk"].balances] == [2_000.0]
        assert len(accounts["roth"].holdings) == 1

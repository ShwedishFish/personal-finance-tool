from datetime import date


def make_account(client, **body):
    resp = client.post("/api/accounts", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_accounts_and_net_worth(client):
    checking = make_account(client, name="Checking", kind="cash", balance=10_000, as_of="2026-01-01")
    make_account(client, name="Card", kind="credit_card", tax_treatment="none", balance=-2_000, as_of="2026-01-01")
    client.post(f"/api/accounts/{checking['id']}/balances", json={"balance": 12_000, "as_of": "2026-02-01"})

    nw = client.get("/api/net-worth").json()
    assert nw["assets"] == 12_000 and nw["liabilities"] == 2_000 and nw["net_worth"] == 10_000
    assert [h["net_worth"] for h in nw["history"]] == [8_000, 10_000]

    resp = client.patch(f"/api/accounts/{checking['id']}", json={"archived": True})
    assert resp.json()["archived"] is True
    assert client.get("/api/net-worth").json()["assets"] == 0


def test_same_day_balance_is_replaced(client):
    acct = make_account(client, name="Savings", kind="cash", balance=100)
    client.post(f"/api/accounts/{acct['id']}/balances", json={"balance": 250})
    balances = client.get(f"/api/accounts/{acct['id']}/balances").json()
    assert len(balances) == 1 and balances[0]["balance"] == 250


def test_plan_projection_uses_accounts_and_cash_flows(client):
    make_account(client, name="401k", kind="retirement", tax_treatment="tax_deferred", balance=200_000,
                 annual_contribution=20_000)
    make_account(client, name="Mortgage", kind="mortgage", tax_treatment="none", balance=300_000,
                 interest_rate=0.06, monthly_payment=2_000)
    plan = client.post("/api/plans", json={"name": "Base", "birth_year": date.today().year - 35}).json()
    for cf in [
        {"name": "Salary", "kind": "income", "amount": 150_000, "ends_at_retirement": True},
        {"name": "Living", "kind": "expense", "amount": 60_000},
        {"name": "Social Security", "kind": "income", "amount": 30_000, "start_age": 67},
        {"name": "Kitchen remodel", "kind": "goal", "amount": 50_000, "start_age": 40},
    ]:
        assert client.post(f"/api/plans/{plan['id']}/cash-flows", json=cf).status_code == 201

    result = client.get(f"/api/plans/{plan['id']}/projection?simulations=100").json()
    assert result["starting"]["tax_deferred"] == 200_000
    assert result["starting"]["liabilities"] == 300_000
    assert result["fi_number"] == 60_000 / 0.04
    years = result["years"]
    assert years[0]["age"] == 35 and years[-1]["age"] == 95
    assert next(y for y in years if y["age"] == 40)["goal_names"] == ["Kitchen remodel"]
    assert 0 <= result["monte_carlo"]["success_rate"] <= 1
    assert result["warnings"] == []


def test_duplicate_plan_copies_cash_flows(client):
    plan = client.post("/api/plans", json={"name": "Base", "birth_year": 1990}).json()
    client.post(f"/api/plans/{plan['id']}/cash-flows", json={"name": "Living", "kind": "expense", "amount": 1})
    copy = client.post(f"/api/plans/{plan['id']}/duplicate").json()
    assert copy["name"] == "Base (copy)" and copy["id"] != plan["id"]
    assert [cf["name"] for cf in copy["cash_flows"]] == ["Living"]
    client.patch(f"/api/plans/{copy['id']}", json={"retirement_age": 55})
    assert client.get(f"/api/plans/{plan['id']}").json()["retirement_age"] == 65


def test_debt_payoff_endpoint(client):
    make_account(client, name="Card", kind="credit_card", tax_treatment="none", balance=5_000,
                 interest_rate=0.24, monthly_payment=200)
    make_account(client, name="Car", kind="loan", tax_treatment="none", balance=8_000,
                 interest_rate=0.05, monthly_payment=250)
    result = client.post("/api/debt/payoff", json={"extra_monthly": 300}).json()
    assert result["paid_off"] and result["strategy"] == "avalanche"
    assert result["comparison"]["strategy"] == "snowball"


def test_plaid_disabled_without_keys(client, monkeypatch):
    from app.config import Settings
    from app.routers import plaid

    monkeypatch.setattr(plaid, "settings", Settings(plaid_client_id="", plaid_secret=""))
    assert client.get("/api/plaid/status").json()["enabled"] is False
    assert client.post("/api/plaid/link-token").status_code == 503

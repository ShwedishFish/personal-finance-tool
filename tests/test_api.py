from datetime import date

import pytest


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
    plan = client.post(
        "/api/plans",
        json={"name": "Base", "birth_year": date.today().year - 35, "pre_medicare_cost": 0, "medicare_cost": 0},
    ).json()
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


def test_children_become_stage_expenses(client):
    year = date.today().year
    plan = client.post("/api/plans", json={"name": "Kids", "birth_year": year - 35}).json()
    client.post(f"/api/plans/{plan['id']}/cash-flows", json={"name": "Spending", "kind": "expense", "amount": 50_000})
    resp = client.post(
        f"/api/plans/{plan['id']}/children",
        json={"name": "Ava", "birth_year": year + 1, "cost_early": 20_000, "cost_middle": 10_000,
              "cost_teen": 15_000, "college_cost": 30_000, "college_years": 4},
    )
    assert resp.status_code == 201
    years = {y["age"]: y for y in client.get(f"/api/plans/{plan['id']}/projection?simulations=0").json()["years"]}
    assert "kids" not in years[35]["expenses_by_category_real"]
    assert years[36]["expenses_by_category_real"]["kids"] == pytest.approx(20_000)
    assert years[36 + 6]["expenses_by_category_real"]["kids"] == pytest.approx(10_000)
    assert years[36 + 18]["expenses_by_category_real"]["education"] == pytest.approx(30_000)
    assert "education" not in years[36 + 22]["expenses_by_category_real"]

    copy = client.post(f"/api/plans/{plan['id']}/duplicate").json()
    assert [c["name"] for c in copy["children"]] == ["Ava"]


def test_social_security_claiming_comparison(client):
    year = date.today().year
    make_account(client, name="IRA", kind="retirement", tax_treatment="tax_deferred", balance=600_000)
    plan = client.post(
        "/api/plans",
        json={"name": "SS", "birth_year": year - 60, "retirement_age": 62, "ss_monthly_benefit": 2_500},
    ).json()
    client.post(f"/api/plans/{plan['id']}/cash-flows", json={"name": "Spending", "kind": "expense", "amount": 50_000})

    proj = client.get(f"/api/plans/{plan['id']}/projection?simulations=0").json()
    assert proj["social_security"] == [{"name": "Social Security", "start_age": 67, "annual": pytest.approx(30_000)}]

    result = client.get(f"/api/plans/{plan['id']}/social-security?simulations=50").json()
    ages = [o["claim_age"] for o in result["options"]]
    assert ages == list(range(62, 71))
    assert result["options"][0]["monthly_benefit"] == pytest.approx(1_750)
    assert result["options"][-1]["monthly_benefit"] == pytest.approx(3_100)
    assert result["best_claim_age"] in ages


def test_social_security_comparison_requires_benefit(client):
    plan = client.post("/api/plans", json={"name": "SS", "birth_year": 1980}).json()
    assert client.get(f"/api/plans/{plan['id']}/social-security").status_code == 400


def test_blank_fields_in_patch_do_not_clear_required_values(client):
    plan = client.post("/api/plans", json={"name": "P", "birth_year": 1990, "spouse_birth_year": 1992}).json()
    resp = client.patch(f"/api/plans/{plan['id']}", json={"retirement_age": None, "spouse_birth_year": None})
    assert resp.status_code == 200
    assert resp.json()["retirement_age"] == 65 and resp.json()["spouse_birth_year"] is None


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

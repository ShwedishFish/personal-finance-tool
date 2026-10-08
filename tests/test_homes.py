from datetime import date

import pytest

from app.finance.projection import HomeInput, ProjectionInput, monthly_mortgage_payment, simulate


def plan(**overrides) -> ProjectionInput:
    base = dict(current_age=40, retirement_age=65, life_expectancy=80, start_year=2026, inflation=0.0,
                tax_mode="flat", effective_tax_rate=0.0, taxable=2_000_000, taxable_basis=2_000_000)
    base.update(overrides)
    return ProjectionInput(**base)


def test_mortgage_payment_formula():
    assert monthly_mortgage_payment(300_000, 0.06, 30) == pytest.approx(1798.65, abs=0.01)
    assert monthly_mortgage_payment(120_000, 0.0, 10) == pytest.approx(1_000)


def test_owned_home_pays_down_mortgage_and_counts_in_net_worth():
    home = HomeInput("House", 500_000, mortgage_balance=300_000, mortgage_payment=1_798.65, mortgage_rate=0.06,
                     carrying_costs=0.02)
    rows = simulate(plan(homes=[home]))
    first = rows[0]
    assert first.debt_payments == pytest.approx(1_798.65 * 12)
    assert first.expenses == pytest.approx(10_000)  # 2% of value
    assert first.home_value == pytest.approx(500_000)
    assert first.home_equity == pytest.approx(500_000 - (300_000 * 1.06 - 1_798.65 * 12))
    assert first.net_worth == pytest.approx(first.investable + first.home_equity)
    paid_off = next(r for r in rows if r.home_equity == pytest.approx(r.home_value))
    assert 28 <= paid_off.age - 40 <= 31


def test_buying_later_takes_down_payment_and_starts_a_mortgage():
    home = HomeInput("Next house", 400_000, purchase_age=45, down_payment=0.2, closing_costs=0.03,
                     mortgage_rate=0.06, mortgage_years=30, appreciation=0.01)
    rows = simulate(plan(inflation=0.02, homes=[home]))
    buy = rows[5]
    price = 400_000 * 1.02 ** 5 * 1.01 ** 5
    assert rows[4].home_value == 0 and rows[4].goals == 0
    assert buy.goals == pytest.approx(price * 0.23)
    assert "Buy Next house" in buy.goal_names
    assert buy.debt_payments == pytest.approx(monthly_mortgage_payment(price * 0.8, 0.06, 30) * 12)
    assert buy.home_value == pytest.approx(price * 1.02 * 1.01)


def test_sale_proceeds_and_taxable_gain_above_exclusion():
    home = HomeInput("House", 1_000_000, cost_basis=200_000, mortgage_balance=0, sale_age=70)
    rows = simulate(plan(homes=[home]))
    sale = rows[30]
    assert sale.home_value == 0 and rows[29].home_value == pytest.approx(1_000_000)
    assert sale.realized_gains == pytest.approx(940_000 - 200_000 - 250_000)
    assert sale.income == pytest.approx(940_000)
    married = simulate(plan(filing_status="married_joint", homes=[home]))[30]
    assert married.realized_gains == pytest.approx(940_000 - 200_000 - 500_000)


def test_downsizing_frees_equity():
    big = HomeInput("Family home", 900_000, sale_age=65)
    small = HomeInput("Condo", 400_000, purchase_age=65, down_payment=1.0, closing_costs=0.02)
    rows = simulate(plan(homes=[big, small]))
    move = rows[25]
    assert move.income == pytest.approx(900_000 * 0.94)
    assert move.goals == pytest.approx(400_000 * 1.02)
    assert move.home_value == pytest.approx(400_000)
    assert move.net_cash_flow == pytest.approx(900_000 * 0.94 - 400_000 * 1.02)


def test_linked_accounts_replace_separate_counting(client):
    prop = client.post("/api/accounts", json={"name": "House", "kind": "property", "tax_treatment": "none",
                                              "balance": 600_000}).json()
    loan = client.post("/api/accounts", json={"name": "Mortgage", "kind": "mortgage", "tax_treatment": "none",
                                              "balance": 300_000, "interest_rate": 0.05,
                                              "monthly_payment": 2_000}).json()
    p = client.post("/api/plans", json={"name": "H", "birth_year": date.today().year - 40,
                                        "pre_medicare_cost": 0, "medicare_cost": 0}).json()
    client.post(f"/api/plans/{p['id']}/cash-flows",
                json={"name": "Living", "kind": "expense", "amount": 40_000})
    proj = client.get(f"/api/plans/{p['id']}/projection?simulations=0").json()
    assert not any("counted twice" in w for w in proj["warnings"])  # no homes yet: nothing to warn

    bad = client.post(f"/api/plans/{p['id']}/homes", json={"name": "Home", "property_account_id": loan["id"]})
    assert bad.status_code == 422
    home = client.post(f"/api/plans/{p['id']}/homes", json={
        "name": "Home", "property_account_id": prop["id"], "mortgage_account_id": loan["id"], "carrying_costs": 0.01,
    }).json()
    first = client.get(f"/api/plans/{p['id']}/projection?simulations=0").json()["years"][0]
    assert first["home_value"] == pytest.approx(600_000 * (1 + p["inflation"]))  # end-of-year value
    assert first["other_assets"] == 0
    assert first["debt_payments"] == pytest.approx(24_000)
    assert first["liabilities"] == pytest.approx(300_000 * 1.05 - 24_000)

    client.patch(f"/api/homes/{home['id']}", json={"property_account_id": None})
    warnings = client.get(f"/api/plans/{p['id']}/projection?simulations=0").json()["warnings"]
    assert any("'House'" in w and "counted twice" in w for w in warnings)
    client.patch(f"/api/homes/{home['id']}", json={"property_account_id": prop["id"]})

    backup = client.get("/api/backup").json()
    client.post("/api/restore", json={"backup": backup, "replace": True})
    accounts = {a["name"]: a["id"] for a in client.get("/api/accounts").json()}
    restored = client.get("/api/plans").json()[0]["homes"][0]
    assert restored["property_account_id"] == accounts["House"]
    assert restored["mortgage_account_id"] == accounts["Mortgage"]

    dup = client.post(f"/api/plans/{client.get('/api/plans').json()[0]['id']}/duplicate").json()
    assert len(dup["homes"]) == 1

from datetime import date

import pytest


def test_csv_import_creates_accounts_and_reports_errors(client):
    client.post("/api/accounts", json={"name": "Checking", "kind": "cash"})
    csv_text = (
        "\ufeffDate,Account,Balance,Kind\n"
        "2026-01-01,checking,\"$1,200.50\",\n"
        "02/01/2026,Checking,1500,\n"
        "02/01/2026,Checking,1600,\n"
        "2026-01-01,Vanguard,50000,brokerage\n"
        "2026-01-01,Car loan,(9000),loan\n"
        "not-a-date,Checking,1,\n"
        "2026-01-01,Mystery,5,spaceship\n"
    )
    result = client.post("/api/import/balances", json={"csv": csv_text}).json()
    assert result["imported"] == 5
    assert result["created_accounts"] == ["Vanguard", "Car loan"]
    assert [e["line"] for e in result["errors"]] == [7, 8]

    accounts = {a["name"]: a for a in client.get("/api/accounts").json()}
    checking = client.get(f"/api/accounts/{accounts['Checking']['id']}/balances").json()
    assert [(b["as_of"], b["balance"]) for b in checking] == [("2026-01-01", 1200.5), ("2026-02-01", 1600)]
    assert accounts["Car loan"]["latest_balance"] == 9000 and accounts["Car loan"]["is_liability"]
    assert accounts["Vanguard"]["tax_treatment"] == "taxable"

    exported = client.get("/api/export/balances.csv")
    assert exported.headers["content-type"].startswith("text/csv")
    lines = exported.text.strip().splitlines()
    assert lines[0] == "date,account,kind,tax_treatment,balance" and len(lines) == 5


def test_csv_import_requires_columns(client):
    resp = client.post("/api/import/balances", json={"csv": "when,amount\n2026-01-01,5\n"})
    assert resp.status_code == 400


def test_roth_conversion_explorer(client):
    year = date.today().year
    client.post("/api/accounts", json={"name": "IRA", "kind": "retirement", "tax_treatment": "tax_deferred",
                                       "balance": 1_500_000})
    client.post("/api/accounts", json={"name": "Brokerage", "kind": "brokerage", "balance": 400_000,
                                       "cost_basis": 250_000})
    plan = client.post("/api/plans", json={"name": "R", "birth_year": year - 60, "retirement_age": 60,
                                           "ss_monthly_benefit": 3_000}).json()
    client.post(f"/api/plans/{plan['id']}/cash-flows", json={"name": "Spending", "kind": "expense", "amount": 70_000})

    result = client.get(f"/api/plans/{plan['id']}/roth-conversions?simulations=50").json()
    assert [o["rate"] for o in result["options"]] == [None, 0.12, 0.22, 0.24, 0.32]
    assert result["window"] == [60, 74]
    none, fill12 = result["options"][0], result["options"][1]
    assert none["total_converted_real"] == 0 and fill12["total_converted_real"] > 0
    assert result["best_rate"] in [o["rate"] for o in result["options"]]

    resp = client.patch(f"/api/plans/{plan['id']}", json={"roth_conversion_rate": 0.22})
    assert resp.json()["roth_conversion_rate"] == 0.22
    years = client.get(f"/api/plans/{plan['id']}/projection?simulations=0").json()["years"]
    assert years[0]["roth_conversion"] > 0
    assert client.patch(f"/api/plans/{plan['id']}", json={"roth_conversion_rate": 0.15}).status_code == 422

    client.patch(f"/api/plans/{plan['id']}", json={"tax_mode": "flat"})
    assert client.get(f"/api/plans/{plan['id']}/roth-conversions").status_code == 400


def test_spouse_without_work_history_gets_spousal_benefit(client):
    year = date.today().year
    plan = client.post("/api/plans", json={
        "name": "S", "birth_year": year - 60, "ss_monthly_benefit": 2_000, "ss_claim_age": 67,
        "spouse_birth_year": year - 58, "spouse_ss_monthly_benefit": 0, "spouse_ss_claim_age": 67,
    }).json()
    ss = client.get(f"/api/plans/{plan['id']}/projection?simulations=0").json()["social_security"]
    assert ss == [
        {"name": "Social Security", "start_age": 67, "annual": pytest.approx(24_000)},
        {"name": "Spousal benefit (spouse)", "start_age": 69, "annual": pytest.approx(12_000)},
    ]

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


def test_backup_round_trip(client):
    year = date.today().year
    acct = client.post("/api/accounts", json={"name": "Brokerage", "kind": "brokerage", "balance": 1000,
                                              "as_of": "2026-01-01", "cost_basis": 600, "owner": "spouse"}).json()
    client.post(f"/api/accounts/{acct['id']}/balances", json={"balance": 1200, "as_of": "2026-02-01"})
    plan = client.post("/api/plans", json={"name": "P", "birth_year": year - 40, "spouse_birth_year": year - 38,
                                           "spouse_retirement_age": 60}).json()
    client.post(f"/api/plans/{plan['id']}/cash-flows",
                json={"name": "Spouse salary", "kind": "income", "amount": 90_000, "owner": "spouse",
                      "ends_at_retirement": True})
    client.post(f"/api/plans/{plan['id']}/children", json={"name": "Ava", "birth_year": year - 2})
    before = client.get(f"/api/plans/{plan['id']}/projection?simulations=0").json()

    resp = client.get("/api/backup")
    assert resp.headers["content-disposition"].startswith("attachment")
    backup = resp.json()
    assert backup["format"] == "personal-finance-tool-backup" and len(backup["accounts"]) == 1

    assert client.post("/api/restore", json={"backup": backup}).status_code == 400  # needs replace=true
    client.post("/api/accounts", json={"name": "Stray", "kind": "cash"})
    restored = client.post("/api/restore", json={"backup": backup, "replace": True}).json()
    assert restored == {"accounts": 1, "plans": 1, "transactions": 0}

    accounts = client.get("/api/accounts").json()
    assert [a["name"] for a in accounts] == ["Brokerage"]
    assert accounts[0]["cost_basis"] == 600 and accounts[0]["owner"] == "spouse"
    assert len(client.get(f"/api/accounts/{accounts[0]['id']}/balances").json()) == 2
    restored = client.get("/api/plans").json()[0]
    assert restored["spouse_retirement_age"] == 60
    assert restored["cash_flows"][0]["owner"] == "spouse" and restored["children"][0]["name"] == "Ava"
    after = client.get(f"/api/plans/{restored['id']}/projection?simulations=0").json()
    assert after["years"] == before["years"]

    bad = dict(backup, format="something-else")
    assert client.post("/api/restore", json={"backup": bad, "replace": True}).status_code == 400
    assert len(client.get("/api/accounts").json()) == 1


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

def test_sample_data_fills_an_empty_app_and_projects(client):
    assert client.get("/api/sample-data").json() == {"loaded": False, "empty": True}
    counts = client.post("/api/sample-data").json()
    assert counts["accounts"] == 10 and counts["plans"] == 1 and counts["transactions"] > 100
    assert client.get("/api/sample-data").json() == {"loaded": True, "empty": False}

    nw = client.get("/api/net-worth").json()
    assert nw["net_worth"] > 0 and len(nw["history"]) > 4
    plan = client.get("/api/plans").json()[0]
    proj = client.get(f"/api/plans/{plan['id']}/projection?simulations=50").json()
    assert 0 <= proj["monte_carlo"]["success_rate"] <= 1
    assert client.get("/api/spending/summary").status_code == 200


def test_sample_data_never_overwrites_real_data(client):
    client.post("/api/accounts", json={"name": "Real checking", "kind": "cash", "balance": 100})
    r = client.post("/api/sample-data")
    assert r.status_code == 409
    assert [a["name"] for a in client.get("/api/accounts").json()] == ["Real checking"]
    assert client.delete("/api/sample-data").status_code == 409


def test_start_fresh_removes_the_sample(client):
    client.post("/api/sample-data")
    assert client.delete("/api/sample-data").status_code == 204
    assert client.get("/api/accounts").json() == []
    assert client.get("/api/plans").json() == []
    assert client.get("/api/sample-data").json() == {"loaded": False, "empty": True}


def test_restoring_a_backup_clears_the_sample_flag(client):
    client.post("/api/sample-data")
    backup = client.get("/api/backup").json()
    client.post("/api/restore", json={"backup": backup, "replace": True})
    assert client.get("/api/sample-data").json()["loaded"] is False

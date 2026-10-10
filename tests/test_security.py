import os
import stat

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import crypto
from app.db import Base, make_engine, upgrade_schema
from app.main import app
from app.models import PlaidItem


def test_plaid_tokens_are_encrypted_at_rest(session_factory):
    with session_factory() as session:
        session.add(PlaidItem(item_id="i1", access_token="access-sandbox-secret"))
        session.commit()
        raw = session.execute(text("SELECT access_token FROM plaid_items")).scalar_one()
        assert raw.startswith(crypto.PREFIX) and "secret" not in raw
        session.expire_all()
        assert session.query(PlaidItem).one().access_token == "access-sandbox-secret"


def test_existing_plaintext_tokens_are_encrypted_on_upgrade():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO plaid_items (item_id, access_token, created_at) VALUES ('i1', 'plain-token', '2025-01-01')"
        ))
    upgrade_schema(engine)
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT access_token FROM plaid_items")).scalar_one()
    assert raw.startswith(crypto.PREFIX) and crypto.decrypt(raw) == "plain-token"


def test_unreadable_token_decrypts_to_empty():
    assert crypto.decrypt(crypto.PREFIX + "not-a-real-token") == ""
    assert crypto.decrypt("legacy-plaintext") == "legacy-plaintext"


def test_key_falls_back_to_private_file(tmp_path, monkeypatch):
    monkeypatch.delenv("PFT_SECRET_KEY")
    monkeypatch.setattr(crypto, "_keyring_get", lambda: None)
    monkeypatch.setattr(crypto, "_keyring_set", lambda key: False)
    monkeypatch.setattr(crypto, "KEY_FILE", tmp_path / "cfg" / "secret.key")
    monkeypatch.setattr(crypto, "_cipher", None)
    token = crypto.encrypt("abc")
    if os.name != "nt":  # Windows has no owner-only mode bits; the user profile folder is private
        assert stat.S_IMODE((tmp_path / "cfg" / "secret.key").stat().st_mode) == 0o600
    assert "key file" in crypto.key_location()
    monkeypatch.setattr(crypto, "_cipher", None)  # reload from the file
    assert crypto.decrypt(token) == "abc"


@pytest.fixture
def no_sleep(monkeypatch):
    from app.routers import auth

    monkeypatch.setattr(auth.time, "sleep", lambda s: None)


def test_password_gates_the_api(client, no_sleep):
    assert client.get("/api/auth/status").json() == {
        "password_enabled": False, "signed_in": True, "bank_links": 0, "key_location": None,
    }
    assert client.put("/api/auth/password", json={"new_password": "short"}).status_code == 422
    assert client.put("/api/auth/password", json={"new_password": "correct horse"}).json() == {"password_enabled": True}
    assert client.get("/api/accounts").status_code == 200  # this browser got a session cookie

    stranger = TestClient(app)
    assert stranger.get("/api/accounts").status_code == 401
    assert stranger.get("/api/auth/status").json() == {"password_enabled": True, "signed_in": False}
    assert stranger.get("/api/health").status_code == 200
    assert stranger.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    stranger.cookies.set("pft_session", "9999999999.forged")
    assert stranger.get("/api/accounts").status_code == 401
    assert stranger.post("/api/auth/login", json={"password": "correct horse"}).status_code == 200
    assert stranger.get("/api/accounts").status_code == 200

    wrong = client.put("/api/auth/password", json={"current_password": "nope", "new_password": "another one"})
    assert wrong.status_code == 403
    change = {"current_password": "correct horse", "new_password": "another one"}
    assert client.put("/api/auth/password", json=change).status_code == 200
    assert stranger.get("/api/accounts").status_code == 401  # changing the password signs others out

    stranger.post("/api/auth/login", json={"password": "another one"})
    stranger.post("/api/auth/logout")
    assert stranger.get("/api/accounts").status_code == 401

    removed = client.put("/api/auth/password", json={"current_password": "another one", "new_password": None})
    assert removed.json() == {"password_enabled": False}
    assert TestClient(app).get("/api/accounts").status_code == 200


def test_rejects_other_host_headers(client):
    assert client.get("/api/health", headers={"host": "attacker.example"}).status_code == 400
    assert client.get("/api/health", headers={"host": "127.0.0.1:8020"}).status_code == 200


def test_pages_may_only_contact_this_app_and_plaid(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self' https://cdn.plaid.com" in csp
    assert "cdn.jsdelivr.net" not in client.get("/").text
    assert client.get("/vendor/chart.umd.min.js").status_code == 200

import json
import os
import stat
from datetime import datetime, timedelta

from app import auto_backup, config


def test_new_installs_keep_data_outside_the_app_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path / "app")
    monkeypatch.setenv("PFT_DATA_DIR", str(tmp_path / "user"))
    assert config.default_database_path() == tmp_path / "user" / "finance.db"


def test_existing_installs_keep_their_database_in_the_app_folder(tmp_path, monkeypatch):
    legacy = tmp_path / "app" / "data" / "finance.db"
    legacy.parent.mkdir(parents=True)
    legacy.touch()
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path / "app")
    monkeypatch.setenv("PFT_DATA_DIR", str(tmp_path / "user"))
    assert config.default_database_path() == legacy


def test_daily_backup_is_written_once_a_day_and_pruned(client, session_factory, tmp_path):
    folder = tmp_path / "backups"
    start = datetime(2026, 1, 1, 9, 0)
    assert auto_backup.run_if_due(folder, session_factory, start) is None  # nothing to back up yet

    client.post("/api/accounts", json={"name": "Checking", "kind": "cash", "balance": 1200})
    first = auto_backup.run_if_due(folder, session_factory, start)
    assert first and json.loads(first.read_text())["accounts"][0]["name"] == "Checking"
    if os.name != "nt":
        assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert auto_backup.run_if_due(folder, session_factory, start + timedelta(hours=23)) is None

    for day in range(1, auto_backup.KEEP + 5):
        auto_backup.run_if_due(folder, session_factory, start + timedelta(days=day))
    files = auto_backup.existing(folder)
    assert len(files) == auto_backup.KEEP
    assert not first.exists()
    assert auto_backup.last_backup(folder) == start + timedelta(days=auto_backup.KEEP + 4)


def test_automatic_backups_restore_with_the_restore_button(client, session_factory, tmp_path):
    client.post("/api/accounts", json={"name": "Checking", "kind": "cash", "balance": 1200})
    path = auto_backup.run_if_due(tmp_path, session_factory)
    client.delete(f"/api/accounts/{client.get('/api/accounts').json()[0]['id']}")
    r = client.post("/api/restore", json={"backup": json.loads(path.read_text()), "replace": True})
    assert r.status_code == 200
    assert [a["name"] for a in client.get("/api/accounts").json()] == ["Checking"]


def test_storage_reports_where_data_lives(client):
    s = client.get("/api/storage").json()
    assert set(s) == {"database", "backups", "last_backup", "keep"}
    assert s["keep"] == auto_backup.KEEP

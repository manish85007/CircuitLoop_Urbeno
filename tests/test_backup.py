import json
from datetime import datetime, timedelta, timezone

import pytest

from app import backup as backup_mod
from app.config import DATA_DIR, STATE_PATH
from app.store import load_state, save_state
from tests.test_api import SEED


def test_health_reports_backup_policy(client):
    res = client.get("/api/health")
    body = res.json()
    assert body["backup"]["keep"] == 1
    assert body["backup"]["dir"].endswith("backups")
    assert "daily at" in body["backup"]["schedule"]
    assert body["backup"]["latest"] is None
    assert body["persist"]["hasState"] is False


def test_backup_skipped_when_no_live_state():
    result = backup_mod.run_backup()
    assert result["ok"] is False
    assert result["previousKept"] is True
    assert backup_mod.latest_backup_dir() is None
    assert not STATE_PATH.exists()


def test_backup_copies_register_and_extra_files():
    save_state(dict(SEED))
    extra = DATA_DIR / "notes.txt"
    extra.write_text("keep me", encoding="utf-8")

    first = backup_mod.run_backup()
    assert first["ok"] is True
    latest = backup_mod.latest_backup_dir()
    assert latest is not None
    copied = json.loads((latest / "circuitloop-state.json").read_text(encoding="utf-8"))
    assert copied["_rev"] == 1
    assert (latest / "notes.txt").read_text(encoding="utf-8") == "keep me"
    assert STATE_PATH.exists()
    assert load_state()["_rev"] == 1


def test_second_backup_deletes_previous_only():
    save_state(dict(SEED))
    first = backup_mod.run_backup()
    live = dict(load_state())
    live["projects"] = list(live["projects"]) + [
        {**SEED["projects"][0], "id": "PRJ-1099", "name": "After first backup"}
    ]
    save_state(live)
    second = backup_mod.run_backup()

    assert second["ok"] is True
    assert first["id"] in second["removed"]
    dirs = backup_mod.list_backup_dirs()
    assert len(dirs) == 1
    assert dirs[0].name == second["id"]
    copied = json.loads((dirs[0] / "circuitloop-state.json").read_text(encoding="utf-8"))
    assert any(p["id"] == "PRJ-1099" for p in copied["projects"])
    still = load_state()
    assert still["_rev"] == 2
    assert any(p["id"] == "PRJ-1099" for p in still["projects"])
    assert STATE_PATH.exists()


def test_failed_backup_keeps_previous(monkeypatch):
    save_state(dict(SEED))
    first = backup_mod.run_backup()
    assert backup_mod.latest_backup_dir().name == first["id"]

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(backup_mod, "_write_staging", boom)
    with pytest.raises(OSError):
        backup_mod.run_backup()

    dirs = backup_mod.list_backup_dirs()
    assert [d.name for d in dirs] == [first["id"]]
    assert load_state()["_rev"] == 1
    assert STATE_PATH.exists()


def test_restore_replaces_live_from_latest_backup():
    save_state(dict(SEED))
    backup_mod.run_backup()
    mutated = dict(load_state())
    mutated["projects"] = []
    STATE_PATH.write_text(json.dumps(mutated), encoding="utf-8")
    assert load_state()["projects"] == []

    restored = backup_mod.restore_latest()
    assert restored["ok"] is True
    live = load_state()
    assert live["projects"][0]["id"] == "PRJ-1001"
    assert live["_rev"] == 1


def test_restore_without_backup_leaves_live_alone():
    save_state(dict(SEED))
    with pytest.raises(FileNotFoundError):
        backup_mod.restore_latest()
    assert load_state()["_rev"] == 1


def test_needs_catchup_and_schedule():
    assert backup_mod.needs_catchup() is True
    save_state(dict(SEED))
    backup_mod.run_backup()
    assert backup_mod.needs_catchup() is False
    later = datetime.now(timezone.utc) + timedelta(hours=21)
    assert backup_mod.needs_catchup(later) is True

    now = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
    wait = backup_mod.seconds_until_next_run(now)
    # Default 18:30 UTC same day.
    assert 8 * 3600 < wait < 9 * 3600
    after = datetime(2026, 9, 19, 18, 31, tzinfo=timezone.utc)
    wait_next = backup_mod.seconds_until_next_run(after)
    assert wait_next > 23 * 3600

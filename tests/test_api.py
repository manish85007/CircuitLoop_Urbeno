import pytest
from fastapi.testclient import TestClient

from app.main import app

SEED = {
    "company": {"name": "Urbeno Technologies Pvt Ltd", "brand": "CircuitLoop Field", "gstin": "27AABCU9603R1ZM", "currency": "INR"},
    "users": [
        {"id": "U-1", "name": "Manish Kumar", "email": "manish85007@gmail.com", "role": "Super Admin", "phone": "", "active": True}
    ],
    "clients": [],
    "projects": [
        {
            "id": "PRJ-1001",
            "name": "Test project",
            "clientId": "CL-1",
            "site": "Pune",
            "mode": "Onsite (Client Premises)",
            "start": "2026-09-01",
            "due": "2026-09-20",
            "status": "Active",
            "managerId": "U-1",
            "team": ["U-1"],
            "scope": [{"category": "Laptop", "expected": 1}],
            "notes": "",
        }
    ],
    "assets": [],
    "manifests": [],
    "categories": ["Laptop"],
    "blanccoCategories": ["Laptop"],
    "blanccoConfig": {
        "endpoint": "https://api.blancco.cloud/v1/erasure-reports",
        "apiKey": "",
        "mode": "Demo (simulated)",
        "autoFetch": True,
        "lastSync": "",
    },
    "testParams": {},
    "specFields": {},
    "seq": {"asset": 1, "usn": 50001, "project": 1004, "client": 4, "user": 6, "blancco": 9001},
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["app"] == "CircuitLoop"
    assert res.json()["brand"] == "Urbeno"
    assert res.json()["persist"]["dataDir"]


def test_index_is_original_field_ui(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "CircuitLoop Field" in res.text
    assert "Urbeno" in res.text
    assert "RECYCLING HEROES" in res.text
    assert "DM Serif Display" in res.text
    assert "#3B6D11" in res.text
    assert "IT Asset Testing" in res.text
    assert "Scan &amp; Test" in res.text or "Scan & Test" in res.text
    assert "/static/persist.js" in res.text
    persist = client.get("/static/persist.js")
    assert persist.status_code == 200
    assert "no-store" in persist.headers.get("cache-control", "")
    assert 'cache: "no-store"' in persist.text or "cache: 'no-store'" in persist.text
    assert "persistInFlight" in persist.text
    assert "persistQueued" in persist.text
    assert "pullIfNewer" in persist.text
    assert "Check in on site" not in res.text


def test_jobs_api_removed(client):
    assert client.get("/api/jobs").status_code == 404


def test_state_roundtrip(client):
    empty = client.get("/api/state")
    assert empty.status_code == 200
    assert empty.json()["state"] is None

    saved = client.put("/api/state", json={"state": SEED})
    assert saved.status_code == 200
    assert saved.json()["state"]["company"]["brand"] == "CircuitLoop Field"

    loaded = client.get("/api/state")
    assert loaded.json()["state"]["projects"][0]["id"] == "PRJ-1001"
    assert loaded.json()["state"]["_rev"] == 1
    assert "no-store" in loaded.headers.get("cache-control", "")


COMPILED_SEED = {
    **SEED,
    "users": [
        {"id": "U-1", "name": "Manish Kumar", "email": "manish85007@gmail.com", "role": "Super Admin", "phone": "", "active": True},
        {"id": "U-2", "name": "S. Iyer", "email": "s.iyer@urbeno.in", "role": "Super Admin", "phone": "", "active": True},
        {"id": "U-3", "name": "A. Verma", "email": "a.verma@urbeno.in", "role": "Field Engineer", "phone": "", "active": True},
        {"id": "U-4", "name": "R. Alvarez", "email": "r.alvarez@urbeno.in", "role": "Field Engineer", "phone": "", "active": True},
        {"id": "U-5", "name": "P. Shetty", "email": "p.shetty@urbeno.in", "role": "Field Engineer", "phone": "", "active": True},
    ],
    "assets": [
        {"id": "A-1", "serial": "DL5540-88213", "category": "Laptop", "brand": "Dell", "model": "Latitude 5540"},
        {"id": "A-2", "serial": "LT14-30291", "category": "Laptop", "brand": "Lenovo", "model": "ThinkPad T14 G4"},
    ],
}


def test_state_last_write_wins_when_behind(client):
    first = client.put("/api/state", json={"state": SEED})
    assert first.status_code == 200
    assert first.json()["state"]["_rev"] == 1

    second = dict(SEED)
    second["projects"] = list(SEED["projects"]) + [
        {**SEED["projects"][0], "id": "PRJ-1002", "name": "Kept"}
    ]
    second["_rev"] = 1
    ok = client.put("/api/state", json={"state": second})
    assert ok.status_code == 200
    assert ok.json()["state"]["_rev"] == 2

    # Overlapping persistNow / beforeunload: same or older hydrated rev still saves.
    behind = dict(second)
    behind["projects"] = list(second["projects"]) + [
        {**SEED["projects"][0], "id": "PRJ-1003", "name": "From overlapping save"}
    ]
    behind["_rev"] = 1
    res = client.put("/api/state", json={"state": behind})
    assert res.status_code == 200
    assert res.json()["state"]["_rev"] == 3
    assert res.json()["state"]["projects"][2]["id"] == "PRJ-1003"


def test_state_rejects_compiled_demo_seed(client):
    live = dict(SEED)
    live["users"] = list(SEED["users"]) + [
        {"id": "U-LEGIT", "name": "Field tester", "email": "tester@urbeno.in", "role": "Field Engineer", "active": True}
    ]
    live["assets"] = [{"id": "A-LIVE", "serial": "LIVE-1", "category": "Laptop"}]
    saved = client.put("/api/state", json={"state": live})
    assert saved.status_code == 200
    assert saved.json()["state"]["_rev"] == 1

    wiped = client.put("/api/state", json={"state": COMPILED_SEED})
    assert wiped.status_code == 409
    body = wiped.json()
    assert "newer copy" in body["error"]
    assert any(u["id"] == "U-LEGIT" for u in body["state"]["users"])
    still = client.get("/api/state")
    assert any(u["id"] == "U-LEGIT" for u in still.json()["state"]["users"])
    assert still.json()["state"]["_rev"] == 1

    # Hydrated client with matching rev can add a user.
    nxt = dict(still.json()["state"])
    nxt["users"] = list(nxt["users"]) + [
        {"id": "U-6", "name": "New engineer", "email": "new@urbeno.in", "role": "Field Engineer", "active": True}
    ]
    ok = client.put("/api/state", json={"state": nxt})
    assert ok.status_code == 200
    assert any(u["id"] == "U-6" for u in ok.json()["state"]["users"])


def test_stale_put_keeps_projects_created_on_another_device(client):
    first = client.put("/api/state", json={"state": SEED})
    assert first.status_code == 200

    device_a = dict(first.json()["state"])
    device_a["projects"] = list(device_a["projects"]) + [
        {**SEED["projects"][0], "id": "PRJ-1004", "name": "MERIDIAN U BUILDING", "team": ["U-6"]}
    ]
    device_a["seq"] = {**SEED["seq"], "project": 1005}
    saved = client.put("/api/state", json={"state": device_a})
    assert saved.status_code == 200
    assert saved.json()["state"]["_rev"] == 2

    device_b = dict(SEED)
    device_b["_rev"] = 1
    device_b["projects"] = list(SEED["projects"]) + [
        {**SEED["projects"][0], "id": "PRJ-1005", "name": "Local only on device B"}
    ]
    merged = client.put("/api/state", json={"state": device_b})
    assert merged.status_code == 200
    ids = [p["id"] for p in merged.json()["state"]["projects"]]
    assert "PRJ-1004" in ids
    assert "PRJ-1005" in ids
    still = client.get("/api/state")
    assert {p["id"] for p in still.json()["state"]["projects"]} >= {"PRJ-1001", "PRJ-1004", "PRJ-1005"}


def test_empty_store_accepts_compiled_seed(client):
    first = client.put("/api/state", json={"state": COMPILED_SEED})
    assert first.status_code == 200
    assert first.json()["state"]["_rev"] == 1
    assert any(a["serial"] == "DL5540-88213" for a in first.json()["state"]["assets"])


def test_state_rejects_partial(client):
    res = client.put("/api/state", json={"state": {"users": []}})
    assert res.status_code == 400


def test_session_and_blancco(client):
    client.put("/api/state", json={"state": SEED})
    auth = client.post("/api/session", json={"userId": "U-1"})
    assert auth.status_code == 200
    assert auth.json()["user"]["role"] == "Super Admin"
    me = client.get("/api/session")
    assert me.json()["user"]["id"] == "U-1"

    demo = client.post("/api/blancco/lookup", json={"serial": "DL5540-88213", "category": "Laptop"})
    assert demo.status_code == 200
    assert demo.json()["ok"] is True
    assert demo.json()["report"]["status"] == "Erased"

    skip = client.post("/api/blancco/lookup", json={"serial": "SW-1", "category": "Switch"})
    assert skip.json()["ok"] is False

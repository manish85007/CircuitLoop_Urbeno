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
    assert 'cache: "no-store"' in persist.text or "cache: 'no-store'" in persist.text
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


def test_state_rejects_stale_revision(client):
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

    stale = dict(SEED)
    stale["_rev"] = 1
    res = client.put("/api/state", json={"state": stale})
    assert res.status_code == 409
    assert res.json()["state"]["projects"][1]["id"] == "PRJ-1002"
    still = client.get("/api/state")
    assert still.json()["state"]["projects"][1]["id"] == "PRJ-1002"
    assert still.json()["state"]["_rev"] == 2


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

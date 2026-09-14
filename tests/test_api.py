from fastapi.testclient import TestClient

from app.main import app

TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
)


def client() -> TestClient:
    return TestClient(app)


def test_health():
    res = client().get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["app"] == "CircuitLoop"
    assert body["brand"] == "Urbeno"


def test_index_serves_field_ui():
    res = client().get("/")
    assert res.status_code == 200
    assert "CircuitLoop" in res.text
    assert "Urbeno" in res.text


def test_session_rejects_bad_pin():
    res = client().post("/api/session", json={"crewName": "Priya Nair", "pin": "0000"})
    assert res.status_code == 401
    assert "PIN" in res.json()["error"]


def test_jobs_require_session():
    res = client().get("/api/jobs")
    assert res.status_code == 401


def test_field_loop_closes_a_job():
    c = client()
    auth = c.post("/api/session", json={"crewName": "Priya Nair", "pin": "4821"})
    assert auth.status_code == 200
    assert auth.json()["crew"]["name"] == "Priya Nair"

    jobs = c.get("/api/jobs?tab=today").json()["jobs"]
    scheduled = next(j for j in jobs if j["status"] == "scheduled")
    job_id = scheduled["id"]

    assert c.post(f"/api/jobs/{job_id}/start-route").status_code == 200
    check = c.post(
        f"/api/jobs/{job_id}/check-in",
        json={"lat": 12.84, "lng": 77.66, "accuracy": 9},
    )
    assert check.status_code == 200
    assert check.json()["job"]["status"] == "on_site"

    added = c.post(
        f"/api/jobs/{job_id}/assets",
        json={
            "category": "laptop",
            "serialNumber": "TEST-001",
            "dataBearing": True,
            "destructionMethod": "wipe",
        },
    )
    assert added.status_code == 200
    assert added.json()["job"]["collected_units"] >= 1

    seal = c.post(
        f"/api/jobs/{job_id}/seals",
        json={"code": "URN-SEAL-TEST", "location": "crate A"},
    )
    assert seal.status_code == 200

    ack = c.post(
        f"/api/jobs/{job_id}/acknowledge",
        json={
            "signerName": "Kavya Iyer",
            "signerRole": "Facilities",
            "signatureDataUrl": TINY_PNG,
        },
    )
    assert ack.status_code == 200

    done = c.post(
        f"/api/jobs/{job_id}/complete",
        json={"overrideNote": "Remaining units not staged for this test close."},
    )
    assert done.status_code == 200
    assert done.json()["job"]["status"] == "complete"

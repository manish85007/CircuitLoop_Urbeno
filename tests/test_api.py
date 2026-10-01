import pyotp

from app.store import empty_production_state, load_state


def enroll_and_login(client, email="manish@urbeno.in"):
    start = client.post("/api/auth/start", json={"email": email})
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["factor"] == "enroll"
    code = pyotp.TOTP(body["secret"]).now()
    verify = client.post("/api/auth/verify", json={"email": email, "code": code})
    assert verify.status_code == 200, verify.text
    assert verify.json()["user"]["email"] == email
    return verify.json()["user"]


def test_health_does_not_leak_paths(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["app"] == "CircuitLoop"
    assert body["persist"]["ready"] is True
    text = res.text
    assert "/data" not in text
    assert "circuitloop-state.json" not in text
    assert body["backup"]["keepDaily"] == 30
    assert body["backup"]["keepMonthly"] == 12

    assert body.get("previewLogin") is False


def test_docs_closed(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_state_requires_session(client):
    res = client.get("/api/state")
    assert res.status_code == 401
    put = client.put("/api/state", json={"state": empty_production_state()})
    assert put.status_code in {401, 405}


def test_click_login_disabled(client):
    res = client.post("/api/session", json={"userId": "U-1"})
    assert res.status_code == 401
    assert "authenticator" in res.json()["error"].lower() or "otp" in res.json()["error"].lower()


def test_unknown_email_rejected(client):
    res = client.post("/api/auth/start", json={"email": "stranger@example.com"})
    assert res.status_code == 401


def test_totp_enroll_and_session(client):
    user = enroll_and_login(client)
    assert user["role"] == "Super Admin"
    assert user["id"] == "U-1"
    me = client.get("/api/session")
    assert me.json()["user"]["email"] == "manish@urbeno.in"
    state = client.get("/api/state")
    assert state.status_code == 200
    body = state.json()["state"]
    assert body["assets"] == []
    assert body["clients"] == []
    assert body["projects"] == []
    emails = {u["email"] for u in body["users"] if u.get("email")}
    assert emails <= {"manish@urbeno.in", "darshak@urbeno.in"}
    assert "apiKey" not in (body.get("blanccoConfig") or {})


def test_field_engineer_sees_assigned_only(client):
    enroll_and_login(client, "manish@urbeno.in")
    client.post("/api/clients", json={"name": "Acme", "blanccoOptIn": True})
    client.post(
        "/api/projects",
        json={
            "name": "Acme refresh",
            "clientId": "CL-1",
            "status": "Active",
            "managerId": "U-1",
            "team": ["U-2"],
            "scope": [{"category": "Laptop", "expected": 2}],
        },
    )
    client.post(
        "/api/assets",
        json={"serial": "SN-1", "projectId": "PRJ-1001", "category": "Laptop", "brand": "Dell", "model": "Lat"},
    )
    client.delete("/api/session")
    enroll_and_login(client, "darshak@urbeno.in")
    state = client.get("/api/state").json()["state"]
    assert state["projects"][0]["id"] == "PRJ-1001"
    assert state["assets"][0]["serial"] == "SN-1"
    assert "gstin" not in state["clients"][0]
    assert all(u.get("email") in {None, "darshak@urbeno.in"} or "email" not in u or u["email"] == "darshak@urbeno.in" for u in state["users"])
    blocked = client.post("/api/clients", json={"name": "Nope"})
    assert blocked.status_code == 403


def test_per_record_asset_and_no_whole_put(client):
    enroll_and_login(client)
    client.post("/api/clients", json={"name": "Client A", "blanccoOptIn": False})
    client.post(
        "/api/projects",
        json={"name": "Job", "clientId": "CL-1", "status": "Active", "team": ["U-1"], "managerId": "U-1"},
    )
    created = client.post(
        "/api/assets",
        json={"serial": "ABC-1", "projectId": "PRJ-1001", "category": "Monitor", "status": "Registered"},
    )
    assert created.status_code == 200
    aid = created.json()["asset"]["id"]
    upd = client.put(f"/api/assets/{aid}", json={"id": aid, "serial": "ABC-1", "projectId": "PRJ-1001", "status": "In Testing", "tests": {"poweron": "Pass"}})
    assert upd.status_code == 200
    rejected = client.put("/api/state", json={"state": empty_production_state()})
    assert rejected.status_code == 405


def test_verified_lock(client):
    enroll_and_login(client)
    client.post("/api/projects", json={"name": "Job", "status": "Active", "team": ["U-1"], "managerId": "U-1"})
    created = client.post(
        "/api/assets",
        json={
            "serial": "LOCK-1",
            "projectId": "PRJ-1001",
            "category": "Monitor",
            "status": "Verified",
            "tests": {"poweron": "Pass"},
            "grade": "A",
        },
    )
    aid = created.json()["asset"]["id"]
    locked = client.put(
        f"/api/assets/{aid}",
        json={"id": aid, "serial": "LOCK-1", "projectId": "PRJ-1001", "status": "Verified", "brand": "Hack"},
    )
    assert locked.status_code == 409
    reopen = client.put(
        f"/api/assets/{aid}",
        json={"id": aid, "serial": "LOCK-1", "projectId": "PRJ-1001", "status": "In Testing", "brand": "Dell"},
    )
    assert reopen.status_code == 200
    assert reopen.json()["asset"]["status"] == "In Testing"


def test_blancco_does_not_simulate(client):
    enroll_and_login(client)
    res = client.post("/api/blancco/lookup", json={"serial": "DL5540-88213", "category": "Laptop"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "simulated" in body["error"].lower() or "API key" in body["error"]
    skip = client.post("/api/blancco/lookup", json={"serial": "NoSerial-1", "category": "Laptop"})
    assert skip.json()["ok"] is False


def test_csv_template_requires_auth(client):
    assert client.get("/api/assets/import-template.csv").status_code == 401
    enroll_and_login(client)
    tpl = client.get("/api/assets/import-template.csv")
    assert tpl.status_code == 200
    assert "Serial*" in tpl.content.decode("utf-8")


def test_index_production_login(client):
    html = client.get("/").text
    assert "CircuitLoop Field" in html
    assert "select a user" not in html.lower()
    assert "Demo build" not in html
    assert "mkAsset(" not in html
    assert "Demo (simulated)" not in html
    assert "persist.js?v=prod13" in html
    assert "qrcode.min.js?v=prod13" in html
    assert "field.js?v=prod13" in html
    assert "integrity=" in html
    field = client.get("/static/field.js")
    assert field.status_code == 200
    assert "function blanccoRequired(a){return false;}" in field.text
    assert "blanccoOptIn" in field.text
    assert "editAssetDetails" in field.text
    assert "function enterField(" in field.text
    assert "function leaveField(" in field.text
    assert "function canonicalizeUser(" in field.text
    assert "function ensureDbLists(" in field.text
    assert "VIEWS.dashboard" in field.text
    assert "data-act=\"addUser\"" in field.text
    assert "Added " in field.text or "Add user" in field.text
    assert "New users cannot be added" not in field.text
    persist = client.get("/static/persist.js")
    assert persist.status_code == 200
    assert "/api/auth/start" in persist.text
    assert "auth_qr" in persist.text
    assert "Email me a code" in persist.text
    assert "openFieldApp" in persist.text
    assert "sessionUserFrom" in persist.text
    assert "Signing in" in persist.text
    assert "we will not send a fake code" in persist.text
    assert "previewCode" in persist.text
    assert "Email a new code" in persist.text
    assert "enterField" in persist.text
    assert "leaveField" in persist.text
    assert "clSignedOut" in persist.text
    assert "paintLive" in persist.text
    assert "dbSeed" in persist.text
    assert "ensureLists" in persist.text
    assert "Object.assign(DB, dbSeed, state)" in persist.text
    assert 'method: "PUT"' not in persist.text
    assert "never writes the demo seed" in persist.text.lower() or "Never writes the demo seed" in persist.text
    qr = client.get("/static/qrcode.min.js")
    assert qr.status_code == 200
    assert b"qrcode" in qr.content[:80]


def test_csv_asset_import_ui(client):
    html = client.get("/").text
    field = client.get("/static/field.js").text
    assert "openAssetCsvImport" in field
    assert "asset-csv.js?v=prod1" in html
    js = client.get("/static/asset-csv.js")
    assert "fillTestsIfTested" in js.text
    assert "CSV Blancco columns ignored" in js.text
    assert "[cosmetic] ?? 1" in js.text or "?? 1" in js.text


def test_asset_csv_parser(client):
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(root / "tests" / "test_asset_csv.js")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_field_shell_after_partial_hydrate(client):
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(root / "tests" / "test_field_shell.js")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_jobs_api_removed(client):
    assert client.get("/api/jobs").status_code == 401


def test_cutover_empty_register(client):
    enroll_and_login(client)
    live = load_state()
    assert live["assets"] == []
    assert live["projects"] == []
    assert {u["email"] for u in live["users"]} == {"manish@urbeno.in", "darshak@urbeno.in"}


def test_sync_upserts_asset(client):
    enroll_and_login(client)
    client.post("/api/projects", json={"name": "Job", "status": "Active", "team": ["U-1"], "managerId": "U-1"})
    res = client.post(
        "/api/sync",
        json={
            "upserts": {
                "assets": [
                    {"serial": "SYNC-1", "projectId": "PRJ-1001", "category": "Laptop", "status": "Registered"}
                ]
            }
        },
    )
    assert res.status_code == 200
    serials = [a["serial"] for a in res.json()["state"]["assets"]]
    assert "SYNC-1" in serials


def test_headers_present(client):
    res = client.get("/api/health")
    assert res.headers.get("x-frame-options") == "DENY"
    csp = res.headers.get("content-security-policy") or ""
    assert "script-src" in csp
    assert "'unsafe-inline'" in csp
    assert res.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert res.json()["emailOtp"] is False
    assert res.json().get("previewLogin") is False


def test_health_email_otp_follows_env(client, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["emailOtp"] is True


def test_verify_sets_session_cookie(client):
    enroll_and_login(client)
    assert client.cookies.get("circuitloop_session")


def test_logout_clears_session_and_rejects_old_cookie(client):
    enroll_and_login(client)
    token = client.cookies.get("circuitloop_session")
    assert token
    assert client.get("/api/state").status_code == 200
    out = client.delete("/api/session")
    assert out.status_code == 200
    assert client.get("/api/session").json()["user"] is None
    assert client.get("/api/state").status_code == 401
    client.cookies.set("circuitloop_session", token)
    assert client.get("/api/session").json()["user"] is None
    assert client.get("/api/state").status_code == 401


def test_preview_login_does_not_reopen_after_sign_out(client, monkeypatch):
    monkeypatch.setenv("PREVIEW_LOGIN", "1")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    opened = client.post("/api/preview/login")
    assert opened.status_code == 200
    assert client.get("/api/session").json()["user"]["id"] == "U-1"
    assert client.delete("/api/session").status_code == 200
    assert client.get("/api/session").json()["user"] is None
    blocked = client.post("/api/preview/login")
    assert blocked.status_code == 401
    assert client.get("/api/session").json()["user"] is None
    assert client.get("/api/state").status_code == 401


def test_verify_and_session_return_super_admin(client):
    user = enroll_and_login(client)
    assert user["id"] == "U-1"
    assert user["role"] == "Super Admin"
    assert user["email"] == "manish@urbeno.in"
    sess = client.get("/api/session").json()["user"]
    assert sess["id"] == "U-1"
    assert sess["email"] == "manish@urbeno.in"
    assert sess["role"] == "Super Admin"
    assert sess["name"]


def test_smtp_transport_is_ipv4_with_465_fallback():
    from pathlib import Path

    from app import auth as auth_mod

    src = Path(auth_mod.__file__).read_text(encoding="utf-8")
    assert "AF_INET" in src
    assert "_IPv4SMTP_SSL" in src
    assert "465" in src
    assert 'local_hostname="localhost"' in src
    assert "api.resend.com" in src
    assert "previewCode" in src


def test_enroll_reuses_secret_and_survives_memory_clear(client):
    first = client.post("/api/auth/start", json={"email": "manish@urbeno.in"})
    assert first.status_code == 200
    body = first.json()
    assert body["factor"] == "enroll"
    assert body["otpauth"].startswith("otpauth://totp/")
    secret = body["secret"]
    second = client.post("/api/auth/start", json={"email": "manish@urbeno.in"})
    assert second.json()["secret"] == secret
    from app import auth as auth_mod

    auth_mod._otp_challenges.clear()
    code = pyotp.TOTP(secret).now()
    verify = client.post("/api/auth/verify", json={"email": "manish@urbeno.in", "code": code})
    assert verify.status_code == 200, verify.text
    assert verify.json()["user"]["email"] == "manish@urbeno.in"


def test_email_otp_not_faked_without_smtp(client):
    res = client.post("/api/auth/start", json={"email": "manish@urbeno.in", "method": "email"})
    assert res.status_code == 400
    assert "authenticator" in res.json()["error"].lower()


def test_preview_email_otp_returns_onscreen_code(client, monkeypatch):
    monkeypatch.setenv("PREVIEW_LOGIN", "1")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    res = client.post("/api/auth/start", json={"email": "manish@urbeno.in", "method": "email"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["factor"] == "email"
    code = body.get("previewCode")
    assert code and len(code) == 6 and code.isdigit()
    assert code in body["message"]
    verify = client.post("/api/auth/verify", json={"email": "manish@urbeno.in", "code": code})
    assert verify.status_code == 200, verify.text
    assert verify.json()["user"]["email"] == "manish@urbeno.in"


def test_health_email_otp_follows_resend_key(client, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_not_real")
    res = client.get("/api/health")
    assert res.json()["emailOtp"] is True


def test_admin_verify_lockout_allows_retries(client):
    enroll_and_login(client)
    client.delete("/api/session")
    for _ in range(13):
        bad = client.post("/api/auth/verify", json={"email": "manish@urbeno.in", "code": "000000"})
        assert bad.status_code == 401
        assert "too many" not in bad.json()["error"].lower()
    start = client.post("/api/auth/start", json={"email": "manish@urbeno.in"})
    assert start.status_code == 200
    assert start.json()["factor"] == "totp"
    from app.config import AUTH_PATH
    import json

    secret = json.loads(AUTH_PATH.read_text())["users"]["manish@urbeno.in"]["totpSecret"]
    code = pyotp.TOTP(secret).now()
    ok = client.post("/api/auth/verify", json={"email": "manish@urbeno.in", "code": code})
    assert ok.status_code == 200, ok.text


def test_old_totp_still_works_during_reenroll(client):
    enroll_and_login(client)
    client.delete("/api/session")
    from app.config import AUTH_PATH
    import json

    old = json.loads(AUTH_PATH.read_text())["users"]["manish@urbeno.in"]["totpSecret"]
    reset = client.post("/api/auth/start", json={"email": "manish@urbeno.in", "method": "enroll"})
    assert reset.status_code == 200
    assert reset.json()["factor"] == "enroll"
    assert reset.json()["secret"] != old
    code = pyotp.TOTP(old).now()
    still = client.post("/api/auth/verify", json={"email": "manish@urbeno.in", "code": code})
    assert still.status_code == 200


def test_preview_login_off_by_default(client):
    res = client.post("/api/preview/login")
    assert res.status_code == 404


def test_preview_login_opens_super_admin(client, monkeypatch):
    monkeypatch.setenv("PREVIEW_LOGIN", "1")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    assert client.get("/api/health").json()["previewLogin"] is True
    res = client.post("/api/preview/login")
    assert res.status_code == 200, res.text
    user = res.json()["user"]
    assert user["email"] == "manish@urbeno.in"
    assert user["role"] == "Super Admin"
    assert user["id"] == "U-1"
    sess = client.get("/api/session").json()["user"]
    assert sess["id"] == "U-1"
    state = client.get("/api/state")
    assert state.status_code == 200
    assert "projects" in state.json()["state"]


def test_super_admin_adds_user_who_can_enroll(client):
    enroll_and_login(client)
    blocked = client.post(
        "/api/users",
        json={"name": "No Email", "role": "Field Engineer"},
    )
    assert blocked.status_code == 400
    created = client.post(
        "/api/users",
        json={
            "name": "Priya Shetty",
            "email": "priya@urbeno.in",
            "role": "Field Engineer",
            "phone": "99999",
        },
    )
    assert created.status_code == 200, created.text
    person = created.json()["user"]
    assert person["id"] == "U-3"
    assert person["email"] == "priya@urbeno.in"
    assert person["role"] == "Field Engineer"
    emails = {u["email"] for u in created.json()["state"]["users"] if u.get("email")}
    assert "priya@urbeno.in" in emails
    dup = client.post(
        "/api/users",
        json={"name": "Priya 2", "email": "priya@urbeno.in", "role": "Field Engineer"},
    )
    assert dup.status_code == 409
    client.delete("/api/session")
    start = client.post("/api/auth/start", json={"email": "priya@urbeno.in"})
    assert start.status_code == 200, start.text
    assert start.json()["factor"] == "enroll"
    code = pyotp.TOTP(start.json()["secret"]).now()
    verify = client.post("/api/auth/verify", json={"email": "priya@urbeno.in", "code": code})
    assert verify.status_code == 200, verify.text
    assert verify.json()["user"]["id"] == "U-3"
    assert verify.json()["user"]["role"] == "Field Engineer"
    sess = client.get("/api/session").json()["user"]
    assert sess["email"] == "priya@urbeno.in"
    add_as_field = client.post(
        "/api/users",
        json={"name": "Nope", "email": "nope@urbeno.in", "role": "Field Engineer"},
    )
    assert add_as_field.status_code == 403


def test_unknown_email_still_rejected_after_roster_grows(client):
    enroll_and_login(client)
    client.post(
        "/api/users",
        json={"name": "Extra", "email": "extra@urbeno.in", "role": "Field Engineer"},
    )
    client.delete("/api/session")
    res = client.post("/api/auth/start", json={"email": "stranger@example.com"})
    assert res.status_code == 401

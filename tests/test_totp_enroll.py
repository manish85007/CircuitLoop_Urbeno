import json

import pyotp

from app.auth import mint_enroll_invite
from app.config import AUTH_PATH
from tests.test_api import enroll_and_login


def _no_secret(body: dict) -> None:
    assert "secret" not in body
    assert "otpauth" not in body
    assert "qr" not in body
    assert "qrcode" not in body


def test_unauthenticated_email_only_does_not_return_qr_or_secret(client):
    for email in ("manish@urbeno.in", "darshak@urbeno.in"):
        for payload in (
            {"email": email},
            {"email": email, "method": "totp"},
            {"email": email, "method": "enroll"},
            {"email": email, "method": "reset"},
            {"email": email, "method": "setup"},
            {"email": email, "method": "qr"},
        ):
            res = client.post("/api/auth/start", json=payload)
            body = res.json()
            _no_secret(body)
            assert res.status_code in {403, 400, 401}
            if payload.get("method") == "enroll" or payload.get("method") in {"reset", "setup"}:
                assert res.status_code == 403

    enrolled = enroll_and_login(client)
    assert enrolled["email"] == "manish@urbeno.in"
    client.delete("/api/session")
    for payload in (
        {"email": "manish@urbeno.in"},
        {"email": "manish@urbeno.in", "method": "enroll"},
        {"email": "darshak@urbeno.in", "method": "totp"},
    ):
        res = client.post("/api/auth/start", json=payload)
        _no_secret(res.json())
        if payload.get("method") in {"enroll", "totp"} and payload["email"] == "darshak@urbeno.in":
            assert res.status_code == 403
        if payload.get("method") == "enroll":
            assert res.status_code == 403
            assert "secret" not in res.json()


def test_enrolled_user_cannot_rotate_without_current_code(client):
    enroll_and_login(client)
    client.delete("/api/session")
    old = json.loads(AUTH_PATH.read_text())["users"]["manish@urbeno.in"]["totpSecret"]
    blocked = client.post("/api/auth/start", json={"email": "manish@urbeno.in", "method": "enroll"})
    assert blocked.status_code == 403
    _no_secret(blocked.json())
    bad = client.post("/api/auth/rotate", json={"email": "manish@urbeno.in", "code": "000000"})
    assert bad.status_code == 401
    _no_secret(bad.json())
    still = json.loads(AUTH_PATH.read_text())["users"]["manish@urbeno.in"]["totpSecret"]
    assert still == old
    ok = client.post("/api/auth/rotate", json={"email": "manish@urbeno.in", "code": pyotp.TOTP(old).now()})
    assert ok.status_code == 200, ok.text
    assert ok.json()["factor"] == "enroll"
    assert ok.json()["secret"] != old
    confirm = client.post(
        "/api/auth/verify",
        json={"email": "manish@urbeno.in", "code": pyotp.TOTP(ok.json()["secret"]).now()},
    )
    assert confirm.status_code == 200, confirm.text


def test_super_admin_can_reset_authenticator(client):
    enroll_and_login(client, "manish@urbeno.in")
    enroll_and_login(client, "darshak@urbeno.in")
    client.delete("/api/session")
    enroll_and_login(client, "manish@urbeno.in")
    old = json.loads(AUTH_PATH.read_text())["users"]["darshak@urbeno.in"]["totpSecret"]
    reset = client.post("/api/users/U-2/reset-authenticator")
    assert reset.status_code == 200, reset.text
    invite = reset.json()
    assert invite["email"] == "darshak@urbeno.in"
    assert invite["inviteToken"]
    assert "secret" not in invite
    rec = json.loads(AUTH_PATH.read_text())["users"]["darshak@urbeno.in"]
    assert not rec.get("totpConfirmed")
    assert rec.get("totpSecret") in (None, "")
    client.delete("/api/session")
    old_code = pyotp.TOTP(old).now()
    dead = client.post("/api/auth/verify", json={"email": "darshak@urbeno.in", "code": old_code})
    assert dead.status_code == 401
    start = client.post(
        "/api/auth/start",
        json={"email": "darshak@urbeno.in", "inviteToken": invite["inviteToken"]},
    )
    assert start.status_code == 200
    assert start.json()["factor"] == "enroll"
    verify = client.post(
        "/api/auth/verify",
        json={"email": "darshak@urbeno.in", "code": pyotp.TOTP(start.json()["secret"]).now()},
    )
    assert verify.status_code == 200


def test_invite_based_first_enroll_works(client):
    enroll_and_login(client)
    created = client.post(
        "/api/users",
        json={"name": "Priya Shetty", "email": "priya@urbeno.in", "role": "Field Engineer"},
    )
    assert created.status_code == 200, created.text
    invite = created.json()["invite"]
    token = invite["inviteToken"]
    client.delete("/api/session")
    denied = client.post("/api/auth/start", json={"email": "priya@urbeno.in", "method": "totp"})
    assert denied.status_code == 403
    _no_secret(denied.json())
    wrong = client.post(
        "/api/auth/start",
        json={"email": "priya@urbeno.in", "inviteToken": "not-the-token"},
    )
    assert wrong.status_code == 401
    _no_secret(wrong.json())
    start = client.post("/api/auth/start", json={"email": "priya@urbeno.in", "inviteToken": token})
    assert start.status_code == 200
    assert start.json()["factor"] == "enroll"
    assert start.json()["otpauth"].startswith("otpauth://totp/")
    verify = client.post(
        "/api/auth/verify",
        json={"email": "priya@urbeno.in", "code": pyotp.TOTP(start.json()["secret"]).now()},
    )
    assert verify.status_code == 200
    assert verify.json()["user"]["email"] == "priya@urbeno.in"
    reused = client.post("/api/auth/start", json={"email": "priya@urbeno.in", "inviteToken": token})
    assert reused.status_code in {401, 409}
    _no_secret(reused.json())


def test_legacy_pending_secret_without_kind_is_not_confirmable(client):
    mint_enroll_invite("manish@urbeno.in")
    rec = json.loads(AUTH_PATH.read_text())
    users = rec.setdefault("users", {})
    users["manish@urbeno.in"] = {
        **users.get("manish@urbeno.in", {}),
        "totpPendingSecret": pyotp.random_base32(),
        "totpPendingKind": None,
        "totpConfirmed": False,
    }
    AUTH_PATH.write_text(json.dumps(rec), encoding="utf-8")
    leaked = json.loads(AUTH_PATH.read_text())["users"]["manish@urbeno.in"]["totpPendingSecret"]
    res = client.post("/api/auth/verify", json={"email": "manish@urbeno.in", "code": pyotp.TOTP(leaked).now()})
    assert res.status_code == 401
    _no_secret(res.json())

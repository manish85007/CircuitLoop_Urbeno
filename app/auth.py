"""Email OTP + TOTP sessions. Roles come from ALLOWED_USERS, never the client."""
from __future__ import annotations

import json
import secrets
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from threading import Lock
from typing import Any

import pyotp
from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.accounts import account_for_email, account_for_id, normalize_email, public_user
from app.audit import append_audit
from app.config import (
    AUTH_PATH,
    BOOTSTRAP_TOKEN,
    COOKIE_NAME,
    SESSION_HOURS,
    SESSION_SECRET,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_STARTTLS,
    SMTP_USER,
    cookie_secure,
    email_otp_enabled,
    ensure_dirs,
)

serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="circuitloop-field")

_lock = Lock()
_otp_challenges: dict[str, dict[str, Any]] = {}
_attempts: dict[str, list[float]] = {}


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_auth() -> dict[str, Any]:
    ensure_dirs()
    if not AUTH_PATH.exists():
        return {"users": {}}
    try:
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"users": {}}
    if not isinstance(data, dict):
        return {"users": {}}
    data.setdefault("users", {})
    return data


def _save_auth(data: dict[str, Any]) -> None:
    ensure_dirs()
    tmp = AUTH_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(AUTH_PATH)


def totp_enrolled(email: str) -> bool:
    key = normalize_email(email)
    with _lock:
        rec = (_load_auth().get("users") or {}).get(key) or {}
    return bool(rec.get("totpConfirmed") and rec.get("totpSecret"))


def _user_auth(email: str) -> dict[str, Any]:
    key = normalize_email(email)
    with _lock:
        return dict((_load_auth().get("users") or {}).get(key) or {})


def _put_user_auth(email: str, patch: dict[str, Any]) -> dict[str, Any]:
    key = normalize_email(email)
    with _lock:
        data = _load_auth()
        users = data.setdefault("users", {})
        row = dict(users.get(key) or {})
        row.update(patch)
        users[key] = row
        _save_auth(data)
        return dict(row)


def _rate_ok(key: str, limit: int, window_sec: int) -> bool:
    now = time.time()
    bucket = [t for t in _attempts.get(key, []) if now - t < window_sec]
    if len(bucket) >= limit:
        _attempts[key] = bucket
        return False
    bucket.append(now)
    _attempts[key] = bucket
    return True


def issue_session(response: Response, user: dict[str, Any]) -> None:
    token = serializer.dumps(
        {
            "userId": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "iat": _utc(),
        }
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def read_session(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = serializer.loads(token, max_age=SESSION_HOURS * 3600)
    except (BadSignature, SignatureExpired):
        return None
    email = normalize_email(payload.get("email"))
    account = account_for_email(email) or account_for_id(payload.get("userId"))
    if not account:
        return None
    # Roles are always taken from the allow-list, never from the cookie.
    return {
        "userId": account["id"],
        "id": account["id"],
        "email": account["email"],
        "name": account["name"],
        "role": account["role"],
    }


def require_user(request: Request) -> dict:
    session = read_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return session


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user.get("role") != "Super Admin":
        raise HTTPException(status_code=403, detail="Super Admin only.")
    return user


def _send_email(to_addr: str, subject: str, body: str) -> None:
    if not SMTP_HOST:
        raise RuntimeError("SMTP is not configured.")
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
        if SMTP_STARTTLS:
            smtp.starttls()
        if SMTP_USER:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(msg)


def start_login(email: str, bootstrap_token: str = "") -> dict[str, Any]:
    addr = normalize_email(email)
    if not _rate_ok("start:" + addr, 8, 900):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    account = account_for_email(addr)
    if account is None:
        # Same wording so the allow-list is not enumerable by timing of a distinct error.
        raise HTTPException(status_code=401, detail="That account cannot sign in.")

    enrolled = totp_enrolled(addr)
    email_on = email_otp_enabled()

    if email_on:
        code = f"{secrets.randbelow(1_000_000):06d}"
        _otp_challenges[addr] = {
            "code": code,
            "exp": time.time() + 600,
            "kind": "email",
        }
        try:
            _send_email(
                addr,
                "CircuitLoop sign-in code",
                f"Your CircuitLoop one-time code is {code}. It expires in 10 minutes.\n",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Could not send email OTP. Use authenticator (TOTP) or check SMTP settings.",
            ) from exc
        append_audit(account, "auth.start", "session", addr, "email OTP sent")
        return {
            "ok": True,
            "email": addr,
            "factor": "email",
            "emailOtp": True,
            "totpEnrolled": enrolled,
            "message": "Enter the 6-digit code emailed to you, or your authenticator code if enrolled.",
        }

    if enrolled:
        append_audit(account, "auth.start", "session", addr, "totp challenge")
        return {
            "ok": True,
            "email": addr,
            "factor": "totp",
            "emailOtp": False,
            "totpEnrolled": True,
            "message": "Enter the 6-digit code from your authenticator app.",
        }

    if BOOTSTRAP_TOKEN and bootstrap_token != BOOTSTRAP_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="First-time authenticator enroll requires BOOTSTRAP_TOKEN.",
        )

    secret = pyotp.random_base32()
    _otp_challenges[addr] = {
        "secret": secret,
        "exp": time.time() + 900,
        "kind": "enroll",
    }
    totp = pyotp.TOTP(secret)
    otpauth = totp.provisioning_uri(name=addr, issuer_name="CircuitLoop")
    append_audit(account, "auth.enroll.start", "session", addr, "totp secret issued")
    return {
        "ok": True,
        "email": addr,
        "factor": "enroll",
        "emailOtp": False,
        "totpEnrolled": False,
        "secret": secret,
        "otpauth": otpauth,
        "message": "Scan the otpauth URL or enter the secret in your authenticator, then confirm with a 6-digit code.",
    }


def verify_login(email: str, code: str, bootstrap_token: str = "") -> dict[str, Any]:
    addr = normalize_email(email)
    if not _rate_ok("verify:" + addr, 12, 900):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    account = account_for_email(addr)
    if account is None:
        raise HTTPException(status_code=401, detail="That account cannot sign in.")
    token = str(code or "").strip().replace(" ", "")
    if not token.isdigit() or len(token) != 6:
        raise HTTPException(status_code=401, detail="Enter the 6-digit verification code.")

    challenge = _otp_challenges.get(addr)
    enrolled_secret = _user_auth(addr).get("totpSecret") if totp_enrolled(addr) else None

    ok = False
    used = ""

    if enrolled_secret and pyotp.TOTP(enrolled_secret).verify(token, valid_window=1):
        ok = True
        used = "totp"

    if not ok and challenge and challenge.get("exp", 0) >= time.time():
        if challenge.get("kind") == "email" and secrets.compare_digest(challenge.get("code", ""), token):
            ok = True
            used = "email"
        elif challenge.get("kind") == "enroll":
            secret = challenge.get("secret") or ""
            if secret and pyotp.TOTP(secret).verify(token, valid_window=1):
                if BOOTSTRAP_TOKEN and bootstrap_token != BOOTSTRAP_TOKEN and not totp_enrolled(addr):
                    raise HTTPException(
                        status_code=401,
                        detail="First-time authenticator enroll requires BOOTSTRAP_TOKEN.",
                    )
                _put_user_auth(
                    addr,
                    {
                        "totpSecret": secret,
                        "totpConfirmed": True,
                        "enrolledAt": _utc(),
                    },
                )
                ok = True
                used = "enroll"

    if not ok:
        raise HTTPException(status_code=401, detail="That code is not valid.")

    _otp_challenges.pop(addr, None)
    append_audit(account, "auth.ok", "session", addr, used)
    return public_user(account, include_contact=True)

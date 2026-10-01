"""Email OTP + TOTP sessions. Roles come from ALLOWED_USERS, never the client."""
from __future__ import annotations

import errno
import json
import secrets
import smtplib
import socket
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from threading import Lock
from typing import Any

import pyotp
from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.accounts import ADMIN_EMAIL, account_for_email, account_for_id, normalize_email, public_user
from app.audit import append_audit
from app.config import (
    AUTH_PATH,
    BOOTSTRAP_TOKEN,
    COOKIE_NAME,
    SESSION_HOURS,
    SESSION_SECRET,
    cookie_secure,
    email_otp_enabled,
    ensure_dirs,
    smtp_settings,
)

serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="circuitloop-field")

_lock = Lock()
# In-memory overlay only. Enroll secrets and email OTPs are also written to AUTH_PATH
# so a Railway restart or a second worker can still verify.
_otp_challenges: dict[str, dict[str, Any]] = {}
_attempts: dict[str, list[float]] = {}

# ±90s of clock skew (three 30s TOTP steps including current).
TOTP_WINDOW = 2
RATE_WINDOW_SEC = 900
# Super Admin must not be stranded by lockout; still cap brute-force.
ADMIN_START_LIMIT = 40
ADMIN_VERIFY_LIMIT = 80
USER_START_LIMIT = 12
USER_VERIFY_LIMIT = 24


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
        for dead in list(row):
            if row[dead] is None:
                row.pop(dead, None)
        users[key] = row
        _save_auth(data)
        return dict(row)


def _rate_limits(email: str) -> tuple[int, int]:
    if normalize_email(email) == ADMIN_EMAIL:
        return ADMIN_START_LIMIT, ADMIN_VERIFY_LIMIT
    return USER_START_LIMIT, USER_VERIFY_LIMIT


def _rate_ok(key: str, limit: int, window_sec: int) -> bool:
    now = time.time()
    bucket = [t for t in _attempts.get(key, []) if now - t < window_sec]
    if len(bucket) >= limit:
        _attempts[key] = bucket
        return False
    bucket.append(now)
    _attempts[key] = bucket
    return True


def _clear_attempts(*keys: str) -> None:
    for key in keys:
        _attempts.pop(key, None)


def _totp_ok(secret: str | None, token: str) -> bool:
    if not secret:
        return False
    try:
        return bool(pyotp.TOTP(str(secret)).verify(token, valid_window=TOTP_WINDOW))
    except Exception:
        return False


def _otpauth(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="CircuitLoop")


def _read_challenge(email: str) -> dict[str, Any] | None:
    addr = normalize_email(email)
    mem = _otp_challenges.get(addr)
    rec = _user_auth(addr).get("otpChallenge")
    disk = rec if isinstance(rec, dict) else None
    candidates = [c for c in (mem, disk) if c]
    now = time.time()
    live = [c for c in candidates if float(c.get("exp") or 0) >= now]
    return live[0] if live else None


def _store_challenge(email: str, challenge: dict[str, Any] | None) -> None:
    addr = normalize_email(email)
    if challenge is None:
        _otp_challenges.pop(addr, None)
        _put_user_auth(addr, {"otpChallenge": None})
        return
    _otp_challenges[addr] = challenge
    _put_user_auth(addr, {"otpChallenge": challenge})


def _require_bootstrap(bootstrap_token: str) -> None:
    if BOOTSTRAP_TOKEN and bootstrap_token != BOOTSTRAP_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="First-time authenticator enroll requires BOOTSTRAP_TOKEN.",
        )


def _pending_or_new_secret(addr: str, bootstrap_token: str, *, replace: bool) -> str:
    rec = _user_auth(addr)
    pending = str(rec.get("totpPendingSecret") or "").strip()
    if pending:
        return pending
    if rec.get("totpConfirmed") and rec.get("totpSecret") and not replace:
        return str(rec["totpSecret"])
    unconfirmed = str(rec.get("totpSecret") or "").strip() if not rec.get("totpConfirmed") else ""
    if unconfirmed:
        _put_user_auth(addr, {"totpPendingSecret": unconfirmed})
        return unconfirmed
    _require_bootstrap(bootstrap_token)
    secret = pyotp.random_base32()
    _put_user_auth(
        addr,
        {
            "totpPendingSecret": secret,
            "totpPendingAt": _utc(),
        },
    )
    return secret


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


def _sanitize_smtp_error(exc: BaseException) -> str:
    cfg = smtp_settings()
    text = f"{type(exc).__name__}: {exc}"
    for secret in (cfg.get("password"), cfg.get("user")):
        if secret:
            text = text.replace(str(secret), "***")
    return text.replace("\n", " ")[:220]


def _ipv4_socket(host: str, port: int, timeout: float) -> socket.socket:
    last: OSError | None = None
    try:
        infos = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_STREAM)
    except OSError as exc:
        raise OSError(f"SMTP IPv4 lookup failed for {host}:{port}") from exc
    for family, socktype, proto, _, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise OSError(f"SMTP IPv4 unreachable ({host}:{port})") from last


class _IPv4SMTP(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        return _ipv4_socket(host, port, timeout)


class _IPv4SMTP_SSL(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        raw = _ipv4_socket(host, port, timeout)
        context = getattr(self, "context", None) or ssl.create_default_context()
        return context.wrap_socket(raw, server_hostname=host)


def _smtp_network_blocked(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, OSError):
        if getattr(exc, "errno", None) in {
            errno.ENETUNREACH,
            errno.EHOSTUNREACH,
            errno.ECONNREFUSED,
            errno.ETIMEDOUT,
            101,
        }:
            return True
        text = str(exc).lower()
        if "unreachable" in text or "timed out" in text or "network is unreachable" in text:
            return True
    return False


def _send_via(cfg: dict[str, Any], msg: EmailMessage, port: int, use_ssl: bool, starttls: bool) -> None:
    timeout = float(cfg.get("timeout") or 12)
    host = cfg["host"]
    cls = _IPv4SMTP_SSL if use_ssl else _IPv4SMTP
    with cls(host, int(port), timeout=timeout) as smtp:
        if starttls and not use_ssl:
            smtp.starttls()
        if cfg["user"]:
            smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)


def _send_email(to_addr: str, subject: str, body: str) -> None:
    cfg = smtp_settings()
    if not cfg["host"]:
        raise RuntimeError("SMTP is not configured.")
    msg = EmailMessage()
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    attempts: list[tuple[int, bool, bool]] = []
    port = int(cfg["port"] or 587)
    use_ssl = bool(cfg.get("ssl") or port == 465)
    starttls = bool(cfg.get("starttls")) and not use_ssl
    attempts.append((port, use_ssl, starttls))
    if port != 465:
        attempts.append((465, True, False))
    last: BaseException | None = None
    for try_port, ssl_on, tls_on in attempts:
        try:
            _send_via(cfg, msg, try_port, ssl_on, tls_on)
            return
        except Exception as exc:
            last = exc
            if _smtp_network_blocked(exc):
                continue
            raise
    assert last is not None
    raise OSError(
        "SMTP blocked from this host (IPv4 "
        + cfg["host"]
        + "). Tried port "
        + str(port)
        + " then 465 SSL. Use authenticator until outbound SMTP is allowed."
    ) from last


def _normalize_method(method: str) -> str:
    choice = str(method or "").strip().lower()
    if choice in {"authenticator", "qr", "otpauth", "app"}:
        return "totp"
    if choice in {"mail", "otp"}:
        return "email"
    if choice in {"reset", "re-enroll", "reenroll", "setup"}:
        return "enroll"
    return choice


def start_login(email: str, bootstrap_token: str = "", method: str = "") -> dict[str, Any]:
    addr = normalize_email(email)
    start_limit, _ = _rate_limits(addr)
    if not _rate_ok("start:" + addr, start_limit, RATE_WINDOW_SEC):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    account = account_for_email(addr)
    if account is None:
        # Same wording so the allow-list is not enumerable by timing of a distinct error.
        raise HTTPException(status_code=401, detail="That account cannot sign in.")

    choice = _normalize_method(method)
    enrolled = totp_enrolled(addr)
    email_on = email_otp_enabled()

    want_email = choice == "email" or (not choice and email_on and not enrolled)
    if choice in {"totp", "enroll"}:
        want_email = False

    if want_email:
        if not email_on:
            raise HTTPException(
                status_code=400,
                detail="Email OTP is not configured. Use authenticator — scan the QR or type the secret.",
            )
        code = f"{secrets.randbelow(1_000_000):06d}"
        _store_challenge(
            addr,
            {
                "code": code,
                "exp": time.time() + 600,
                "kind": "email",
            },
        )
        try:
            _send_email(
                addr,
                "CircuitLoop sign-in code",
                f"Your CircuitLoop one-time code is {code}. It expires in 10 minutes.\n",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Could not send email OTP ("
                + _sanitize_smtp_error(exc)
                + "). Use authenticator or check SMTP settings.",
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

    replace = choice == "enroll" and enrolled
    if enrolled and not replace:
        append_audit(account, "auth.start", "session", addr, "totp challenge")
        return {
            "ok": True,
            "email": addr,
            "factor": "totp",
            "emailOtp": email_on,
            "totpEnrolled": True,
            "message": "Enter the 6-digit code from your authenticator app.",
        }

    secret = _pending_or_new_secret(addr, bootstrap_token, replace=replace)
    otpauth = _otpauth(secret, addr)
    append_audit(account, "auth.enroll.start", "session", addr, "totp secret issued")
    return {
        "ok": True,
        "email": addr,
        "factor": "enroll",
        "emailOtp": email_on,
        "totpEnrolled": enrolled,
        "secret": secret,
        "otpauth": otpauth,
        "message": "Scan the QR in Google Authenticator, Authy, or 1Password (or type the secret), then confirm with a 6-digit code.",
    }


def verify_login(email: str, code: str, bootstrap_token: str = "") -> dict[str, Any]:
    addr = normalize_email(email)
    _, verify_limit = _rate_limits(addr)
    if not _rate_ok("verify:" + addr, verify_limit, RATE_WINDOW_SEC):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    account = account_for_email(addr)
    if account is None:
        raise HTTPException(status_code=401, detail="That account cannot sign in.")
    token = str(code or "").strip().replace(" ", "")
    if not token.isdigit() or len(token) != 6:
        raise HTTPException(status_code=401, detail="Enter the 6-digit verification code.")

    rec = _user_auth(addr)
    challenge = _read_challenge(addr)
    confirmed_secret = rec.get("totpSecret") if rec.get("totpConfirmed") else None
    pending_secret = str(rec.get("totpPendingSecret") or "").strip()
    if not pending_secret and challenge and challenge.get("kind") == "enroll":
        pending_secret = str(challenge.get("secret") or "").strip()
    if not pending_secret and rec.get("totpSecret") and not rec.get("totpConfirmed"):
        pending_secret = str(rec.get("totpSecret") or "").strip()

    ok = False
    used = ""

    if confirmed_secret and _totp_ok(confirmed_secret, token):
        ok = True
        used = "totp"

    if not ok and pending_secret and _totp_ok(pending_secret, token):
        if BOOTSTRAP_TOKEN and bootstrap_token != BOOTSTRAP_TOKEN and not totp_enrolled(addr):
            raise HTTPException(
                status_code=401,
                detail="First-time authenticator enroll requires BOOTSTRAP_TOKEN.",
            )
        _put_user_auth(
            addr,
            {
                "totpSecret": pending_secret,
                "totpConfirmed": True,
                "totpPendingSecret": None,
                "totpPendingAt": None,
                "enrolledAt": rec.get("enrolledAt") or _utc(),
            },
        )
        ok = True
        used = "enroll" if not confirmed_secret else "reenroll"

    if not ok and challenge and challenge.get("kind") == "email":
        expected = str(challenge.get("code") or "")
        if expected and secrets.compare_digest(expected, token):
            ok = True
            used = "email"

    if not ok:
        raise HTTPException(
            status_code=401,
            detail="That authenticator code is not valid. If it keeps failing, set up a new QR and delete old CircuitLoop entries in the app.",
        )

    _store_challenge(addr, None)
    _clear_attempts("start:" + addr, "verify:" + addr)
    append_audit(account, "auth.ok", "session", addr, used)
    return public_user(account, include_contact=True)

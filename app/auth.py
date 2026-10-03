"""Email OTP + TOTP sessions. Roles come from seed accounts or the live register."""
from __future__ import annotations

import errno
import hashlib
import json
import secrets
import smtplib
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
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
    COOKIE_NAME,
    SESSION_HOURS,
    SESSION_SECRET,
    cookie_secure,
    cors_origin_list,
    email_otp_enabled,
    ensure_dirs,
    http_mail_settings,
    on_railway,
    preview_login_enabled,
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
INVITE_TTL_SEC = 48 * 3600
PENDING_KINDS = frozenset({"invite", "rotate"})
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


def _hash_invite(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _clear_pending(addr: str, extra: dict[str, Any] | None = None) -> None:
    patch: dict[str, Any] = {
        "totpPendingSecret": None,
        "totpPendingAt": None,
        "totpPendingKind": None,
    }
    if extra:
        patch.update(extra)
    _put_user_auth(addr, patch)


def _invite_row(rec: dict[str, Any]) -> dict[str, Any]:
    row = rec.get("enrollInvite")
    return dict(row) if isinstance(row, dict) else {}


def public_origin() -> str:
    for origin in cors_origin_list():
        text = str(origin or "").strip().rstrip("/")
        if "loop.urbeno.in" in text:
            return text
    origins = [o.strip().rstrip("/") for o in cors_origin_list() if o.strip() and o.strip() != "*"]
    return origins[0] if origins else "https://loop.urbeno.in"


def invite_url(email: str, token: str) -> str:
    addr = normalize_email(email)
    query = urllib.parse.urlencode({"email": addr})
    return public_origin() + "/?" + query + "#invite=" + urllib.parse.quote(token, safe="")


def mint_enroll_invite(email: str, *, actor_id: str = "", purpose: str = "first") -> str:
    addr = normalize_email(email)
    token = secrets.token_urlsafe(32)
    _put_user_auth(
        addr,
        {
            "enrollInvite": {
                "hash": _hash_invite(token),
                "exp": time.time() + INVITE_TTL_SEC,
                "issuedAt": _utc(),
                "issuedBy": actor_id or "",
                "purpose": purpose if purpose in {"first", "reset"} else "first",
            }
        },
    )
    return token


def issue_enroll_invite(admin: dict[str, Any], email: str, *, purpose: str = "first") -> dict[str, Any]:
    if not admin or admin.get("role") != "Super Admin":
        raise HTTPException(status_code=403, detail="Super Admin only.")
    addr = normalize_email(email)
    account = _resolve_login_account(email=addr)
    if account is None or account.get("active") is False:
        raise HTTPException(status_code=404, detail="User not found.")
    if purpose == "first" and totp_enrolled(addr):
        raise HTTPException(
            status_code=409,
            detail="This account already has an authenticator. Use Reset authenticator.",
        )
    if purpose == "reset":
        bump_session_version(addr)
        _put_user_auth(
            addr,
            {
                "totpSecret": None,
                "totpConfirmed": False,
                "totpPendingSecret": None,
                "totpPendingAt": None,
                "totpPendingKind": None,
            },
        )
    token = mint_enroll_invite(addr, actor_id=str(admin.get("id") or ""), purpose=purpose)
    emailed = False
    url = invite_url(addr, token)
    try:
        emailed = bool(
            _send_email(
                addr,
                "CircuitLoop authenticator invite",
                "A Super Admin invited you to set up a CircuitLoop authenticator.\n\n"
                "Open this link on a trusted device (it expires in 48 hours):\n"
                + url
                + "\n\nIf you did not expect this, tell a Super Admin.\n",
            )
        )
    except Exception:
        emailed = False
    append_audit(admin, "auth.invite", "session", addr, purpose + (" emailed" if emailed else ""))
    rec = _user_auth(addr)
    inv = _invite_row(rec)
    return {
        "ok": True,
        "email": addr,
        "userId": account.get("id"),
        "inviteToken": token,
        "inviteUrl": url,
        "expiresAt": _utc_from_epoch(float(inv.get("exp") or 0)),
        "emailed": emailed,
        "purpose": purpose,
    }


def _utc_from_epoch(exp: float) -> str:
    if not exp:
        return ""
    return datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pending_secret_for_invite(addr: str, invite_token: str) -> str:
    rec = _user_auth(addr)
    inv = _invite_row(rec)
    stored = str(inv.get("hash") or "")
    token = str(invite_token or "").strip()
    if not stored or not token or len(stored) != 64:
        raise HTTPException(status_code=401, detail="That invite is not valid or has expired.")
    if not secrets.compare_digest(stored, _hash_invite(token)):
        raise HTTPException(status_code=401, detail="That invite is not valid or has expired.")
    try:
        exp = float(inv.get("exp") or 0)
    except (TypeError, ValueError):
        exp = 0
    if exp < time.time():
        raise HTTPException(status_code=401, detail="That invite is not valid or has expired.")
    purpose = str(inv.get("purpose") or "first")
    if totp_enrolled(addr) and purpose != "reset":
        raise HTTPException(
            status_code=409,
            detail="This account already has an authenticator. Ask a Super Admin to reset it.",
        )
    pending = str(rec.get("totpPendingSecret") or "").strip()
    if pending and rec.get("totpPendingKind") == "invite":
        return pending
    secret = pyotp.random_base32()
    _put_user_auth(
        addr,
        {
            "totpPendingSecret": secret,
            "totpPendingAt": _utc(),
            "totpPendingKind": "invite",
        },
    )
    return secret


def _enroll_payload(addr: str, secret: str, enrolled: bool, email_on: bool, message: str) -> dict[str, Any]:
    return {
        "ok": True,
        "email": addr,
        "factor": "enroll",
        "emailOtp": email_on,
        "totpEnrolled": enrolled,
        "secret": secret,
        "otpauth": _otpauth(secret, addr),
        "message": message,
    }


def issue_session(response: Response, user: dict[str, Any]) -> None:
    token = serializer.dumps(
        {
            "userId": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "sv": _session_version(user.get("email")),
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
    _clear_signed_out_cookie(response)


SIGNED_OUT_COOKIE = "circuitloop_signed_out"


def _session_version(email: str | None) -> int:
    rec = _user_auth(normalize_email(email))
    try:
        return int(rec.get("sessionVersion") or 1)
    except (TypeError, ValueError):
        return 1


def bump_session_version(email: str | None) -> None:
    addr = normalize_email(email)
    if not addr:
        return
    rec = _user_auth(addr)
    try:
        current = int(rec.get("sessionVersion") or 1)
    except (TypeError, ValueError):
        current = 1
    _put_user_auth(addr, {"sessionVersion": current + 1})


def _cookie_clear_kwargs() -> dict:
    return {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
    }


def _expire_named_cookie(response: Response, name: str) -> None:
    kwargs = _cookie_clear_kwargs()
    for secure in (True, False):
        response.delete_cookie(name, secure=secure, **kwargs)
        response.set_cookie(
            name,
            "",
            max_age=0,
            expires=0,
            httponly=True,
            samesite="lax",
            secure=secure,
            path="/",
        )


def clear_session(response: Response) -> None:
    # Delete both Secure and non-Secure variants so HTTPS and local cookies actually leave the browser.
    _expire_named_cookie(response, COOKIE_NAME)


def mark_signed_out(response: Response) -> None:
    response.set_cookie(
        SIGNED_OUT_COOKIE,
        "1",
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
    )


def _clear_signed_out_cookie(response: Response) -> None:
    _expire_named_cookie(response, SIGNED_OUT_COOKIE)


def signed_out_blocked(request: Request) -> bool:
    return str(request.cookies.get(SIGNED_OUT_COOKIE) or "") == "1"


def peek_session_payload(request: Request) -> dict[str, Any] | None:
    """Signed cookie payload without role/sessionVersion checks — used to revoke on Sign out."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = serializer.loads(token, max_age=SESSION_HOURS * 3600)
    except (BadSignature, SignatureExpired):
        return None
    return payload if isinstance(payload, dict) else None


def discard_invalid_session_cookie(request: Request, response: Response) -> None:
    if not request.cookies.get(COOKIE_NAME):
        return
    if read_session(request) is None:
        clear_session(response)


def end_session(request: Request, response: Response) -> None:
    peeked = peek_session_payload(request)
    email = normalize_email((peeked or {}).get("email"))
    if not email:
        session = read_session(request)
        email = normalize_email((session or {}).get("email"))
    if email:
        bump_session_version(email)
    clear_session(response)
    mark_signed_out(response)


def _resolve_login_account(email: str | None = None, user_id: str | None = None) -> dict[str, Any] | None:
    from app.store import resolve_account

    return resolve_account(email=email, user_id=user_id)


def read_session(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = serializer.loads(token, max_age=SESSION_HOURS * 3600)
    except (BadSignature, SignatureExpired):
        return None
    email = normalize_email(payload.get("email"))
    account = _resolve_login_account(email=email, user_id=payload.get("userId"))
    if not account or account.get("active") is False:
        return None
    try:
        cookie_sv = int(payload.get("sv") or 1)
    except (TypeError, ValueError):
        cookie_sv = 0
    if cookie_sv != _session_version(account.get("email")):
        return None
    # Roles come from the seed list or the live register, never from the cookie.
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
    from app.store import is_super_admin

    if not is_super_admin(user):
        raise HTTPException(status_code=403, detail="Super Admin only.")
    return user


def _sanitize_smtp_error(exc: BaseException) -> str:
    cfg = smtp_settings()
    http = http_mail_settings()
    text = f"{type(exc).__name__}: {exc}"
    secrets_to_hide = [
        cfg.get("password"),
        cfg.get("user"),
        http.get("resend"),
        http.get("sendgrid"),
        http.get("mailgun_key"),
    ]
    for secret in secrets_to_hide:
        if secret:
            text = text.replace(str(secret), "***")
    return text.replace("\n", " ")[:220]


def _smtp_socket(host: str, port: int, timeout: float) -> socket.socket:
    """Connect without getfqdn(). Try IPv4 then IPv6 with a short timeout (Railway IPv6 is often ENETUNREACH)."""
    last: OSError | None = None
    deadline = time.time() + max(1.0, float(timeout))
    for family in (socket.AF_INET, socket.AF_INET6):
        remaining = deadline - time.time()
        if remaining <= 0.05:
            break
        try:
            infos = socket.getaddrinfo(host, int(port), family, socket.SOCK_STREAM)
        except OSError as exc:
            last = exc
            continue
        for fam, socktype, proto, _, sockaddr in infos[:3]:
            remaining = deadline - time.time()
            if remaining <= 0.05:
                break
            sock = socket.socket(fam, socktype, proto)
            sock.settimeout(min(remaining, max(1.0, float(timeout))))
            try:
                sock.connect(sockaddr)
                return sock
            except OSError as exc:
                last = exc
                sock.close()
    raise OSError(f"SMTP unreachable ({host}:{port})") from last


class _DirectSMTP(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        return _smtp_socket(host, port, timeout)


class _DirectSMTP_SSL(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        raw = _smtp_socket(host, port, timeout)
        context = getattr(self, "context", None) or ssl.create_default_context()
        return context.wrap_socket(raw, server_hostname=host)


def _smtp_network_blocked(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, FuturesTimeout, socket.timeout)):
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
        if "unreachable" in text or "timed out" in text or "timeout" in text or "network is unreachable" in text:
            return True
    return False


def _smtp_blocked_message(host: str, ports: list[int]) -> str:
    tried = ", ".join(str(p) for p in ports)
    if on_railway():
        return (
            "SMTP blocked from this host ("
            + str(host)
            + "). Tried "
            + tried
            + ". Railway Hobby/Trial drops outbound 25/465/587, so Gmail SMTP cannot send. "
            "On the web service set RESEND_API_KEY (or SENDGRID_API_KEY, or MAILGUN_API_KEY and MAILGUN_DOMAIN). "
            "SMTP_HOST/SMTP_USER/SMTP_PASSWORD need Railway Pro plus a redeploy. Use authenticator until then."
        )
    return (
        "SMTP blocked from this host ("
        + str(host)
        + "). Tried "
        + tried
        + ". Check outbound 25/465/587, credentials, and that the from-address is allowed. "
        "HTTPS mail (RESEND_API_KEY, SENDGRID_API_KEY, or MAILGUN_API_KEY + MAILGUN_DOMAIN) is the fallback. "
        "Authenticator still works."
    )


def _send_via(cfg: dict[str, Any], msg: EmailMessage, port: int, use_ssl: bool, starttls: bool) -> None:
    timeout = min(3.0, max(1.5, float(cfg.get("timeout") or 2)))
    host = cfg["host"]
    cls = _DirectSMTP_SSL if use_ssl else _DirectSMTP
    with cls(host, int(port), local_hostname="localhost", timeout=timeout) as smtp:
        smtp.ehlo()
        if starttls and not use_ssl:
            smtp.starttls()
            smtp.ehlo()
        if cfg["user"]:
            smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)


def _send_smtp(cfg: dict[str, Any], msg: EmailMessage) -> None:
    port = int(cfg["port"] or 587)
    ordered: list[tuple[int, bool, bool]] = [(465, True, False), (587, False, True)]
    if port not in {465, 587}:
        use_ssl = bool(cfg.get("ssl") or port == 465)
        starttls = bool(cfg.get("starttls")) and not use_ssl
        ordered.insert(0, (port, use_ssl, starttls))
    last: BaseException | None = None
    for try_port, ssl_on, tls_on in ordered:
        try:
            _send_via(cfg, msg, try_port, ssl_on, tls_on)
            return
        except Exception as exc:
            last = exc
            if _smtp_network_blocked(exc):
                continue
            raise
    assert last is not None
    raise OSError(_smtp_blocked_message(str(cfg["host"]), [p for p, _, _ in ordered])) from last


def _http_post(url: str, data: bytes, headers: dict[str, str], timeout: float = 8) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            if int(getattr(resp, "status", 200) or 200) >= 400:
                raise RuntimeError("Email API HTTP " + str(resp.status))
            return body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:180]
        raise RuntimeError("Email API HTTP " + str(exc.code) + " " + detail) from exc


def _send_http_mail(to_addr: str, subject: str, body: str) -> bool:
    http = http_mail_settings()
    cfg = smtp_settings()
    from_addr = cfg["from_addr"] or http.get("mailgun_domain") or "circuitloop@urbeno.in"
    if http["resend"]:
        payload = json.dumps({"from": from_addr, "to": [to_addr], "subject": subject, "text": body}).encode()
        _http_post(
            "https://api.resend.com/emails",
            payload,
            {"Authorization": "Bearer " + http["resend"], "Content-Type": "application/json"},
        )
        return True
    if http["sendgrid"]:
        payload = json.dumps(
            {
                "personalizations": [{"to": [{"email": to_addr}]}],
                "from": {"email": from_addr},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            }
        ).encode()
        _http_post(
            "https://api.sendgrid.com/v3/mail/send",
            payload,
            {"Authorization": "Bearer " + http["sendgrid"], "Content-Type": "application/json"},
        )
        return True
    if http["mailgun_key"] and http["mailgun_domain"]:
        import base64
        from urllib.parse import urlencode

        token = base64.b64encode(("api:" + http["mailgun_key"]).encode()).decode()
        form = urlencode(
            {"from": from_addr, "to": to_addr, "subject": subject, "text": body}
        ).encode()
        _http_post(
            "https://api.mailgun.net/v3/" + http["mailgun_domain"] + "/messages",
            form,
            {"Authorization": "Basic " + token, "Content-Type": "application/x-www-form-urlencoded"},
        )
        return True
    return False


def _mail_can_deliver() -> bool:
    cfg = smtp_settings()
    http = http_mail_settings()
    return bool(cfg["host"] or http["resend"] or http["sendgrid"] or (http["mailgun_key"] and http["mailgun_domain"]))


def _send_email(to_addr: str, subject: str, body: str) -> bool:
    """Return True if a provider accepted the message."""
    http_err: BaseException | None = None
    try:
        if _send_http_mail(to_addr, subject, body):
            return True
    except Exception as exc:
        http_err = exc
    cfg = smtp_settings()
    if cfg["host"]:
        msg = EmailMessage()
        msg["From"] = cfg["from_addr"]
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)
        timeout = min(8.0, max(4.0, float(cfg.get("timeout") or 2) * 2 + 2))
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_send_smtp, cfg, msg)
            try:
                fut.result(timeout=timeout)
            except FuturesTimeout as exc:
                raise OSError("SMTP send timed out after " + str(int(timeout)) + "s") from (http_err or exc)
        return True
    if http_err:
        raise http_err
    if preview_login_enabled():
        return False
    raise RuntimeError("SMTP is not configured.")


def _normalize_method(method: str) -> str:
    choice = str(method or "").strip().lower()
    if choice in {"authenticator", "qr", "otpauth", "app"}:
        return "totp"
    if choice in {"mail", "otp"}:
        return "email"
    if choice in {"reset", "re-enroll", "reenroll", "setup"}:
        return "enroll"
    return choice


def start_login(
    email: str,
    bootstrap_token: str = "",
    method: str = "",
    invite_token: str = "",
) -> dict[str, Any]:
    addr = normalize_email(email)
    start_limit, _ = _rate_limits(addr)
    if not _rate_ok("start:" + addr, start_limit, RATE_WINDOW_SEC):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    account = _resolve_login_account(email=addr)
    if account is None or account.get("active") is False:
        # Same wording so the roster is not enumerable by timing of a distinct error.
        raise HTTPException(status_code=401, detail="That account cannot sign in.")

    choice = _normalize_method(method)
    enrolled = totp_enrolled(addr)
    email_on = email_otp_enabled()
    invite = str(invite_token or "").strip()

    if invite:
        secret = _pending_secret_for_invite(addr, invite)
        append_audit(account, "auth.enroll.start", "session", addr, "invite totp secret issued")
        return _enroll_payload(
            addr,
            secret,
            enrolled,
            email_on,
            "Scan the QR in Google Authenticator, Authy, or 1Password (or type the secret), then confirm with a 6-digit code.",
        )

    if choice == "enroll":
        raise HTTPException(
            status_code=403,
            detail="Re-enroll requires your current authenticator code or a Super Admin reset.",
        )

    want_email = choice == "email" or (not choice and email_on and not enrolled)
    if choice == "totp":
        want_email = False

    if want_email:
        if not email_on:
            raise HTTPException(
                status_code=400,
                detail="Email OTP is not configured. Use authenticator if you already enrolled, or ask a Super Admin for an invite.",
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
        delivered = False
        send_err: BaseException | None = None
        try:
            delivered = bool(_send_email(
                addr,
                "CircuitLoop sign-in code",
                f"Your CircuitLoop one-time code is {code}. It expires in 10 minutes.\n",
            ))
        except Exception as exc:
            send_err = exc
            delivered = False
        preview = preview_login_enabled()
        if not delivered and not preview:
            raise HTTPException(
                status_code=503,
                detail="Could not send email OTP ("
                + _sanitize_smtp_error(send_err or RuntimeError("SMTP is not configured."))
                + "). Use authenticator, or set RESEND_API_KEY / SENDGRID_API_KEY / MAILGUN_API_KEY on the web service.",
            ) from send_err
        append_audit(
            account,
            "auth.start",
            "session",
            addr,
            "email OTP sent" if delivered else "email OTP preview",
        )
        payload = {
            "ok": True,
            "email": addr,
            "factor": "email",
            "emailOtp": True,
            "totpEnrolled": enrolled,
            "message": "Enter the 6-digit code emailed to you, or your authenticator code if enrolled.",
        }
        if preview and not delivered:
            payload["previewCode"] = code
            payload["message"] = (
                "Preview only — email was not sent. Your code is "
                + code
                + ". Production needs working SMTP or RESEND_API_KEY."
            )
        return payload

    if enrolled:
        append_audit(account, "auth.start", "session", addr, "totp challenge")
        return {
            "ok": True,
            "email": addr,
            "factor": "totp",
            "emailOtp": email_on,
            "totpEnrolled": True,
            "message": "Enter the 6-digit code from your authenticator app.",
        }

    raise HTTPException(
        status_code=403,
        detail="Ask a Super Admin to send an authenticator invite before first sign-in.",
    )


def start_rotate(email: str, current_code: str) -> dict[str, Any]:
    addr = normalize_email(email)
    start_limit, _ = _rate_limits(addr)
    if not _rate_ok("rotate:" + addr, start_limit, RATE_WINDOW_SEC):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    account = _resolve_login_account(email=addr)
    if account is None or account.get("active") is False:
        raise HTTPException(status_code=401, detail="That account cannot sign in.")
    if not totp_enrolled(addr):
        raise HTTPException(
            status_code=403,
            detail="Ask a Super Admin to send an authenticator invite before first sign-in.",
        )
    token = str(current_code or "").strip().replace(" ", "")
    rec = _user_auth(addr)
    if not token.isdigit() or len(token) != 6 or not _totp_ok(rec.get("totpSecret"), token):
        raise HTTPException(status_code=401, detail="That authenticator code is not valid.")
    pending = str(rec.get("totpPendingSecret") or "").strip()
    if pending and rec.get("totpPendingKind") == "rotate":
        secret = pending
    else:
        secret = pyotp.random_base32()
        _put_user_auth(
            addr,
            {
                "totpPendingSecret": secret,
                "totpPendingAt": _utc(),
                "totpPendingKind": "rotate",
            },
        )
    append_audit(account, "auth.enroll.start", "session", addr, "rotate totp secret issued")
    return _enroll_payload(
        addr,
        secret,
        True,
        email_otp_enabled(),
        "Scan the new QR, then confirm with a 6-digit code from the new authenticator entry. Your current code still works until then.",
    )


def verify_login(email: str, code: str, bootstrap_token: str = "") -> dict[str, Any]:
    addr = normalize_email(email)
    _, verify_limit = _rate_limits(addr)
    if not _rate_ok("verify:" + addr, verify_limit, RATE_WINDOW_SEC):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    account = _resolve_login_account(email=addr)
    if account is None or account.get("active") is False:
        raise HTTPException(status_code=401, detail="That account cannot sign in.")
    token = str(code or "").strip().replace(" ", "")
    if not token.isdigit() or len(token) != 6:
        raise HTTPException(status_code=401, detail="Enter the 6-digit verification code.")

    rec = _user_auth(addr)
    challenge = _read_challenge(addr)
    confirmed_secret = rec.get("totpSecret") if rec.get("totpConfirmed") else None
    pending_kind = str(rec.get("totpPendingKind") or "")
    pending_secret = str(rec.get("totpPendingSecret") or "").strip()
    if pending_kind not in PENDING_KINDS:
        pending_secret = ""

    ok = False
    used = ""

    if confirmed_secret and _totp_ok(confirmed_secret, token):
        ok = True
        used = "totp"
        if rec.get("totpPendingSecret") or rec.get("totpPendingKind"):
            _clear_pending(addr)

    if not ok and pending_secret and _totp_ok(pending_secret, token):
        _put_user_auth(
            addr,
            {
                "totpSecret": pending_secret,
                "totpConfirmed": True,
                "totpPendingSecret": None,
                "totpPendingAt": None,
                "totpPendingKind": None,
                "enrollInvite": None,
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
            detail="That authenticator code is not valid. Ask a Super Admin to reset the authenticator if you no longer have the current code.",
        )

    _store_challenge(addr, None)
    _clear_attempts("start:" + addr, "verify:" + addr)
    append_audit(account, "auth.ok", "session", addr, used)
    return public_user(account, include_contact=True)

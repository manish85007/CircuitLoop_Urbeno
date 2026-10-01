import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "43180"))
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data"))).resolve()
STATE_PATH = Path(os.environ.get("STATE_PATH", str(DATA_DIR / "circuitloop-state.json")))
AUTH_PATH = Path(os.environ.get("AUTH_PATH", str(DATA_DIR / "auth.json")))
AUDIT_PATH = Path(os.environ.get("AUDIT_PATH", str(DATA_DIR / "audit.jsonl")))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(DATA_DIR / "backups"))).resolve()
BACKUP_HOUR_UTC = int(os.environ.get("BACKUP_HOUR_UTC", "18"))
BACKUP_MINUTE_UTC = int(os.environ.get("BACKUP_MINUTE_UTC", "30"))
BACKUP_STARTUP_DELAY_SEC = float(os.environ.get("BACKUP_STARTUP_DELAY_SEC", "20"))
BACKUP_STALE_HOURS = float(os.environ.get("BACKUP_STALE_HOURS", "20"))
BACKUP_KEEP_DAILY = int(os.environ.get("BACKUP_KEEP_DAILY", "30"))
BACKUP_KEEP_MONTHLY = int(os.environ.get("BACKUP_KEEP_MONTHLY", "12"))
SESSION_SECRET = os.environ.get(
    "SESSION_SECRET", "local-dev-circuitloop-not-for-production"
)
BLANCCO_API_KEY = os.environ.get("BLANCCO_API_KEY", "")
BLANCCO_ENDPOINT = os.environ.get(
    "BLANCCO_ENDPOINT", "https://api.blancco.cloud/v1/erasure-reports"
)
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "https://loop.urbeno.in")
COOKIE_NAME = "circuitloop_session"
SESSION_HOURS = 16
APP_NAME = "CircuitLoop"
BRAND = "CircuitLoop"
SCHEMA_VERSION = "production-v1"
CUTOVER_ID = "2026-10-01-production-harden"

def _env_str(name: str, default: str = "") -> str:
    text = str(os.environ.get(name, default) or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def smtp_settings() -> dict:
    host = _env_str("SMTP_HOST")
    user = _env_str("SMTP_USER")
    port_raw = _env_str("SMTP_PORT", "587") or "587"
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    starttls = _env_str("SMTP_STARTTLS", "1").lower() not in {"0", "false", "no", "off"}
    ssl_raw = _env_str("SMTP_SSL", "1" if port == 465 else "0").lower()
    use_ssl = ssl_raw not in {"0", "false", "no", "off"} or port == 465
    if use_ssl:
        starttls = False
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": _env_str("SMTP_PASSWORD"),
        "from_addr": _env_str("SMTP_FROM", user or "circuitloop@urbeno.in") or (user or "circuitloop@urbeno.in"),
        "starttls": starttls,
        "ssl": use_ssl,
        "timeout": float(_env_str("SMTP_TIMEOUT", "5") or "5"),
    }


def http_mail_settings() -> dict:
    return {
        "resend": _env_str("RESEND_API_KEY"),
        "sendgrid": _env_str("SENDGRID_API_KEY"),
        "mailgun_key": _env_str("MAILGUN_API_KEY"),
        "mailgun_domain": _env_str("MAILGUN_DOMAIN"),
    }


# Snapshots for local defaults; request paths re-read via smtp_settings().
SMTP_HOST = smtp_settings()["host"]
SMTP_PORT = smtp_settings()["port"]
SMTP_USER = smtp_settings()["user"]
SMTP_PASSWORD = smtp_settings()["password"]
SMTP_FROM = smtp_settings()["from_addr"]
SMTP_STARTTLS = smtp_settings()["starttls"]

BOOTSTRAP_TOKEN = os.environ.get("BOOTSTRAP_TOKEN", "").strip()


def email_otp_enabled() -> bool:
    if preview_login_enabled():
        return True
    status = email_delivery_public()
    return bool(status["smtpConfigured"] or status["httpsConfigured"])


def email_delivery_public() -> dict:
    """Health-safe mail status. Never includes host, user, or secrets."""
    cfg = smtp_settings()
    http = http_mail_settings()
    smtp = bool(cfg["host"])
    https_provider = None
    if http["resend"]:
        https_provider = "resend"
    elif http["sendgrid"]:
        https_provider = "sendgrid"
    elif http["mailgun_key"] and http["mailgun_domain"]:
        https_provider = "mailgun"
    https = https_provider is not None
    hint = ""
    if https:
        hint = "Email OTP is sent over HTTPS."
    elif smtp and is_production():
        hint = (
            "SMTP is set on this web process, but Railway Hobby/Trial blocks outbound "
            "ports 25/465/587 (Gmail SMTP cannot send). On the web service set RESEND_API_KEY, "
            "or SENDGRID_API_KEY, or MAILGUN_API_KEY and MAILGUN_DOMAIN. "
            "SMTP_HOST/SMTP_USER/SMTP_PASSWORD only work after a Railway Pro upgrade and redeploy. "
            "Authenticator still works."
        )
    elif smtp:
        hint = "Email OTP will use SMTP."
    elif preview_login_enabled():
        hint = "Preview: email codes show on the login card when SMTP/HTTPS is not configured."
    else:
        hint = (
            "Email OTP is off. On the web service set RESEND_API_KEY "
            "(or SENDGRID_API_KEY, or MAILGUN_API_KEY and MAILGUN_DOMAIN), "
            "or SMTP_HOST/SMTP_USER/SMTP_PASSWORD on Railway Pro."
        )
    return {
        "smtpConfigured": smtp,
        "httpsConfigured": https,
        "httpsProvider": https_provider,
        "hint": hint,
    }


def cookie_secure() -> bool:
    raw = os.environ.get("COOKIE_SECURE", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return os.environ.get("RAILWAY_ENVIRONMENT") is not None or str(DATA_DIR) == "/data"


def backup_enabled() -> bool:
    return os.environ.get("BACKUP_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def is_production() -> bool:
    return str(DATA_DIR) == "/data" or os.environ.get("RAILWAY_ENVIRONMENT") is not None


def preview_login_enabled() -> bool:
    """Local Preview only. Never on Railway or a Secure cookie host."""
    if is_production():
        return False
    if cookie_secure():
        return False
    return os.environ.get("PREVIEW_LOGIN", "").strip().lower() in {"1", "true", "yes", "on"}


def cors_origin_list() -> list[str]:
    if CORS_ORIGINS.strip() == "*":
        return ["*"]
    return [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

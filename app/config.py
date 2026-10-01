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

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "circuitloop@urbeno.in")
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

BOOTSTRAP_TOKEN = os.environ.get("BOOTSTRAP_TOKEN", "").strip()


def email_otp_enabled() -> bool:
    return bool(SMTP_HOST)


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


def cors_origin_list() -> list[str]:
    if CORS_ORIGINS.strip() == "*":
        return ["*"]
    return [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

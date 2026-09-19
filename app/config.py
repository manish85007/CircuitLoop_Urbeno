import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "43180"))
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data"))).resolve()
STATE_PATH = Path(os.environ.get("STATE_PATH", str(DATA_DIR / "circuitloop-state.json")))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(DATA_DIR / "backups"))).resolve()
BACKUP_HOUR_UTC = int(os.environ.get("BACKUP_HOUR_UTC", "18"))
BACKUP_MINUTE_UTC = int(os.environ.get("BACKUP_MINUTE_UTC", "30"))
BACKUP_STARTUP_DELAY_SEC = float(os.environ.get("BACKUP_STARTUP_DELAY_SEC", "20"))
BACKUP_STALE_HOURS = float(os.environ.get("BACKUP_STALE_HOURS", "20"))
SESSION_SECRET = os.environ.get(
    "SESSION_SECRET", "local-dev-circuitloop-not-for-production"
)
BLANCCO_API_KEY = os.environ.get("BLANCCO_API_KEY", "")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
COOKIE_NAME = "circuitloop_session"
SESSION_HOURS = 16
APP_NAME = "CircuitLoop"
BRAND = "CircuitLoop"


def backup_enabled() -> bool:
    return os.environ.get("BACKUP_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

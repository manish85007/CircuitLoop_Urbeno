import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "43180"))
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data"))).resolve()
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", str(DATA_DIR / "circuitloop.db")))
MEDIA_DIR = DATA_DIR / "media"
SESSION_SECRET = os.environ.get(
    "SESSION_SECRET", "local-dev-circuitloop-not-for-production"
)
CREW_PIN = os.environ.get("CREW_PIN", "4821")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
COOKIE_NAME = "circuitloop_session"
SESSION_HOURS = 16
APP_NAME = "CircuitLoop"
BRAND = "Urbeno"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TMP = tempfile.mkdtemp(prefix="circuitloop-test-")
os.environ["DATA_DIR"] = TMP
os.environ["SESSION_SECRET"] = "test-secret-circuitloop"
os.environ["STATE_PATH"] = str(Path(TMP) / "state.json")
os.environ["AUTH_PATH"] = str(Path(TMP) / "auth.json")
os.environ["AUDIT_PATH"] = str(Path(TMP) / "audit.jsonl")
os.environ["BACKUP_ENABLED"] = "0"
os.environ["BACKUP_DIR"] = str(Path(TMP) / "backups")
os.environ["COOKIE_SECURE"] = "0"
os.environ["CORS_ORIGINS"] = "http://testserver"
os.environ.pop("SMTP_HOST", None)
os.environ.pop("BOOTSTRAP_TOKEN", None)
os.environ.pop("RAILWAY_ENVIRONMENT", None)

from app.main import app  # noqa: E402
from app.config import AUTH_PATH, DATA_DIR  # noqa: E402
from app import auth as auth_mod  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_state():
    path = Path(os.environ["STATE_PATH"])
    if path.exists():
        path.unlink()
    tmp = path.with_suffix(".json.tmp")
    if tmp.exists():
        tmp.unlink()
    for extra in (AUTH_PATH, Path(os.environ["AUDIT_PATH"])):
        if extra.exists():
            extra.unlink()
    for marker in DATA_DIR.glob(".cutover-*"):
        marker.unlink()
    backups = Path(os.environ["BACKUP_DIR"])
    if backups.exists():
        shutil.rmtree(backups)
    auth_mod._otp_challenges.clear()
    auth_mod._attempts.clear()
    yield

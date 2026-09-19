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
os.environ["BACKUP_ENABLED"] = "0"
os.environ["BACKUP_DIR"] = str(Path(TMP) / "backups")

from app.main import app  # noqa: E402


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
    backups = Path(os.environ["BACKUP_DIR"])
    if backups.exists():
        shutil.rmtree(backups)
    yield

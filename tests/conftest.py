import os
import tempfile
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp(prefix="circuitloop-test-")
os.environ["DATA_DIR"] = TMP
os.environ["SESSION_SECRET"] = "test-secret-circuitloop"
os.environ["STATE_PATH"] = str(Path(TMP) / "state.json")


@pytest.fixture(autouse=True)
def _clean_state():
    path = Path(os.environ["STATE_PATH"])
    if path.exists():
        path.unlink()
    tmp = path.with_suffix(".json.tmp")
    if tmp.exists():
        tmp.unlink()
    yield

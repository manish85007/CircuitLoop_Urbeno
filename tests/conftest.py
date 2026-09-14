import os
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="circuitloop-test-")
os.environ["DATA_DIR"] = TMP
os.environ["SESSION_SECRET"] = "test-secret-circuitloop"
os.environ["STATE_PATH"] = str(Path(TMP) / "state.json")

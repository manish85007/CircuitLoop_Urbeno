import os
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="circuitloop-test-")
os.environ["DATA_DIR"] = TMP
os.environ["SESSION_SECRET"] = "test-secret-circuitloop"
os.environ["CREW_PIN"] = "4821"
os.environ["DATABASE_PATH"] = str(Path(TMP) / "test.db")

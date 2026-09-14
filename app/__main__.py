"""Start uvicorn bound to $PORT without shell expansion.

Railway execs the start command as argv, so `${PORT:-8080}` is passed
to uvicorn as a literal. Read the env var in Python instead.
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    port = os.environ.get("PORT", "8080")
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
        ],
    )


if __name__ == "__main__":
    main()

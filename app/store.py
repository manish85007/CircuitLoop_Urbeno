from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.config import STATE_PATH, ensure_dirs

_lock = Lock()

REQUIRED = ("company", "users", "clients", "projects", "assets")


class StaleState(Exception):
    """Client tried to save an older copy over a newer register."""

    def __init__(self, current: dict[str, Any]):
        self.current = current
        super().__init__(
            "A newer copy of the register is already saved. Refresh and try again."
        )


def load_state() -> dict[str, Any] | None:
    ensure_dirs()
    if not STATE_PATH.exists():
        return None
    with _lock:
        raw = STATE_PATH.read_text(encoding="utf-8")
    if not raw.strip():
        return None
    return json.loads(raw)


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise TypeError("State must be JSON.")
    missing = [k for k in REQUIRED if k not in state]
    if missing:
        raise ValueError("State is missing: " + ", ".join(missing))
    ensure_dirs()
    with _lock:
        current = None
        if STATE_PATH.exists():
            raw = STATE_PATH.read_text(encoding="utf-8")
            if raw.strip():
                current = json.loads(raw)
        if current:
            cur_rev = int(current.get("_rev") or 0)
            incoming = int(state.get("_rev") or 0)
            if incoming < cur_rev:
                raise StaleState(current)
            state["_rev"] = cur_rev + 1
        else:
            state["_rev"] = 1
        state["_savedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        encoded = json.dumps(state, ensure_ascii=False)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(encoded, encoding="utf-8")
        tmp.replace(STATE_PATH)
    return state

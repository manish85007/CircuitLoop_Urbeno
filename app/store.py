from __future__ import annotations

import json
from threading import Lock
from typing import Any

from app.config import STATE_PATH, ensure_dirs

_lock = Lock()

REQUIRED = ("company", "users", "clients", "projects", "assets")


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
    missing = [k for k in REQUIRED if k not in state]
    if missing:
        raise ValueError("State is missing: " + ", ".join(missing))
    ensure_dirs()
    encoded = json.dumps(state, ensure_ascii=False)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    with _lock:
        tmp.write_text(encoded, encoding="utf-8")
        tmp.replace(STATE_PATH)
    return state

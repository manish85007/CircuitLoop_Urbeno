from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.config import STATE_PATH, ensure_dirs

_lock = Lock()

REQUIRED = ("company", "users", "clients", "projects", "assets")

# Fingerprint of static/index.html `const DB={...}` + mkAsset demo rows.
# A hydrated client always has `_rev >= 1`; only this blob is posted with no rev.
DEMO_USER_IDS = frozenset({"U-1", "U-2", "U-3", "U-4", "U-5"})
DEMO_EMAILS = frozenset(
    {
        "manish85007@gmail.com",
        "s.iyer@urbeno.in",
        "a.verma@urbeno.in",
        "r.alvarez@urbeno.in",
        "p.shetty@urbeno.in",
    }
)
DEMO_SERIAL = "DL5540-88213"


class StaleState(Exception):
    """Compiled demo seed (or other unhydrated PUT) would wipe the register."""

    def __init__(self, current: dict[str, Any]):
        self.current = current
        super().__init__(
            "A newer copy of the register is already saved. Refresh and try again."
        )


def _ids(records: Any, key: str = "id") -> set[str]:
    out: set[str] = set()
    for row in records or []:
        if isinstance(row, dict) and row.get(key):
            out.add(str(row[key]))
    return out


def is_compiled_demo_seed(state: dict[str, Any]) -> bool:
    """True for the Field HTML demo DB, not a hydrated user/test save."""
    incoming = int(state.get("_rev") or 0)
    if incoming >= 1:
        return False
    users = state.get("users") or []
    ids = {str(u.get("id")) for u in users if isinstance(u, dict) and u.get("id")}
    emails = {
        str(u.get("email") or "").strip().lower()
        for u in users
        if isinstance(u, dict)
    }
    if ids != DEMO_USER_IDS:
        return False
    if not DEMO_EMAILS.issubset(emails):
        return False
    serials = _ids(state.get("assets"), "serial")
    return DEMO_SERIAL in serials


def _would_drop_records(current: dict[str, Any], incoming: dict[str, Any]) -> bool:
    lost_users = _ids(current.get("users")) - _ids(incoming.get("users"))
    lost_serials = _ids(current.get("assets"), "serial") - _ids(incoming.get("assets"), "serial")
    return bool(lost_users or lost_serials)


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
            incoming_rev = int(state.get("_rev") or 0)
            # Unhydrated PUTs: the compiled demo (no `_rev`) or any body that
            # would delete users/serials. Hydrated clients (`_rev >= 1`) last-write-wins,
            # including overlapping same-rev saves from persistNow + beforeunload.
            if incoming_rev < 1 and (
                is_compiled_demo_seed(state) or _would_drop_records(current, state)
            ):
                raise StaleState(current)
            state["_rev"] = int(current.get("_rev") or 0) + 1
        else:
            state["_rev"] = 1
        state["_savedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        encoded = json.dumps(state, ensure_ascii=False)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(encoded, encoding="utf-8")
        tmp.replace(STATE_PATH)
    return state

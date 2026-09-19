from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.config import STATE_PATH, ensure_dirs

_lock = Lock()

REQUIRED = ("company", "users", "clients", "projects", "assets")
LIST_KEYS = ("users", "clients", "projects", "assets", "manifests")

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


def _merge_by_id(incoming_list: Any, current_list: Any) -> list[Any]:
    """Keep every id from current; incoming overwrites overlapping ids and appends new ones."""
    by_id: dict[str, dict[str, Any]] = {}
    incoming_only: list[Any] = []
    for row in current_list or []:
        if isinstance(row, dict) and row.get("id"):
            by_id[str(row["id"])] = row
    for row in incoming_list or []:
        if isinstance(row, dict) and row.get("id"):
            by_id[str(row["id"])] = row
        elif isinstance(row, dict):
            incoming_only.append(row)
    out: list[Any] = []
    seen: set[str] = set()
    for row in current_list or []:
        if not isinstance(row, dict) or not row.get("id"):
            out.append(row)
            continue
        key = str(row["id"])
        if key in seen:
            continue
        out.append(by_id[key])
        seen.add(key)
    for row in incoming_list or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        key = str(row["id"])
        if key in seen:
            continue
        out.append(row)
        seen.add(key)
    out.extend(incoming_only)
    return out


def _merge_seq(current: Any, incoming: Any) -> dict[str, Any]:
    cur = current if isinstance(current, dict) else {}
    inc = incoming if isinstance(incoming, dict) else {}
    keys = set(cur) | set(inc)
    out: dict[str, Any] = {}
    for key in keys:
        cv, iv = cur.get(key), inc.get(key)
        try:
            out[key] = max(int(cv or 0), int(iv or 0))
        except (TypeError, ValueError):
            out[key] = iv if iv is not None else cv
    return out


def merge_state(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Union collections so a stale device cannot drop projects created elsewhere."""
    out = dict(incoming)
    for key in LIST_KEYS:
        out[key] = _merge_by_id(incoming.get(key), current.get(key))
    out["seq"] = _merge_seq(current.get("seq"), incoming.get("seq"))
    for key, value in current.items():
        if key in ("_rev", "_savedAt"):
            continue
        if key not in out:
            out[key] = value
    return out


def snapshot_state_bytes() -> bytes | None:
    """Read the live register under the write lock. Does not modify production data."""
    ensure_dirs()
    with _lock:
        if not STATE_PATH.exists():
            return None
        raw = STATE_PATH.read_bytes()
    if not raw.strip():
        return None
    return raw


def replace_state_bytes(raw: bytes) -> None:
    """Atomically replace the live register. Used only by restore, never by backup."""
    if not raw.strip():
        raise ValueError("Backup is empty; live register was not changed.")
    json.loads(raw.decode("utf-8"))
    ensure_dirs()
    with _lock:
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_bytes(raw)
        tmp.replace(STATE_PATH)


def load_state() -> dict[str, Any] | None:
    raw = snapshot_state_bytes()
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


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
            cur_rev = int(current.get("_rev") or 0)
            # Unhydrated PUTs: the compiled demo (no `_rev`) or any body that
            # would delete users/serials.
            if incoming_rev < 1 and (
                is_compiled_demo_seed(state) or _would_drop_records(current, state)
            ):
                raise StaleState(current)
            # Older hydrated copy from another device/tab: keep local edits
            # and restore any records the stale body omitted (e.g. PRJ-1004).
            if incoming_rev < cur_rev:
                state = merge_state(current, state)
            state["_rev"] = cur_rev + 1
        else:
            state["_rev"] = 1
        state["_savedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        encoded = json.dumps(state, ensure_ascii=False)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(encoded, encoding="utf-8")
        tmp.replace(STATE_PATH)
    return state

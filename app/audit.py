"""Append-only server audit trail. Never rewritten; client history is not authoritative."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.config import AUDIT_PATH, ensure_dirs

_lock = Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_audit(
    actor: dict[str, Any] | None,
    action: str,
    entity: str,
    entity_id: str = "",
    detail: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "ts": _now(),
        "action": action,
        "entity": entity,
        "entityId": entity_id,
        "detail": detail,
        "userId": (actor or {}).get("id") or (actor or {}).get("userId") or "",
        "email": (actor or {}).get("email") or "",
        "name": (actor or {}).get("name") or "",
        "role": (actor or {}).get("role") or "",
    }
    if extra:
        row["extra"] = extra
    ensure_dirs()
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        with AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    return row


def recent_audit(limit: int = 200) -> list[dict[str, Any]]:
    if not AUDIT_PATH.exists():
        return []
    with _lock:
        raw = AUDIT_PATH.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]

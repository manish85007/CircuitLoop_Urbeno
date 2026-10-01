"""Production register: empty seed, one-shot wipe, per-record mutations, role views."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from fastapi import HTTPException

from app.accounts import ALLOWED_USERS, account_for_id, public_user
from app.audit import append_audit
from app.config import (
    BLANCCO_API_KEY,
    BLANCCO_ENDPOINT,
    CUTOVER_ID,
    DATA_DIR,
    SCHEMA_VERSION,
    STATE_PATH,
    ensure_dirs,
)
from app.masters import BLANCCO_CATEGORIES, CATEGORIES, SPEC_FIELDS, TEST_PARAMS

_lock = Lock()

REQUIRED = ("company", "users", "clients", "projects", "assets")
LIST_KEYS = ("users", "clients", "projects", "assets", "manifests")
ASSET_STATUSES = {"Registered", "In Testing", "Tested", "Verified", "Rejected"}
ROLES = {"Super Admin", "Field Engineer"}
ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,40}$")
SERIAL_RE = re.compile(r"^.{1,80}$")

DEMO_USER_EMAILS = frozenset(
    {
        "manish85007@gmail.com",
        "s.iyer@urbeno.in",
        "a.verma@urbeno.in",
        "r.alvarez@urbeno.in",
        "p.shetty@urbeno.in",
    }
)
DEMO_PROJECT_IDS = frozenset({"PRJ-1001", "PRJ-1002", "PRJ-1003"})
SIMULATED_MARKERS = ("demo (simulated)", "csv import", "failseed")


class StaleState(Exception):
    def __init__(self, current: dict[str, Any], message: str | None = None):
        self.current = current
        super().__init__(message or "Not saved — a newer copy of this record is on the server.")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%d %H:%M")


def _cutover_marker() -> Any:
    return DATA_DIR / f".cutover-{CUTOVER_ID}"


def empty_production_state() -> dict[str, Any]:
    users = [copy.deepcopy(u) for u in ALLOWED_USERS.values()]
    return {
        "_schema": SCHEMA_VERSION,
        "company": {
            "name": "Urbeno Technologies Pvt Ltd",
            "brand": "CircuitLoop Field",
            "gstin": "",
            "currency": "INR",
        },
        "users": users,
        "clients": [],
        "projects": [],
        "assets": [],
        "manifests": [],
        "categories": list(CATEGORIES),
        "blanccoCategories": list(BLANCCO_CATEGORIES),
        "blanccoConfig": {
            "endpoint": BLANCCO_ENDPOINT,
            "mode": "Live" if BLANCCO_API_KEY else "Off",
            "autoFetch": True,
            "lastSync": "",
            "hasApiKey": bool(BLANCCO_API_KEY),
        },
        "testParams": copy.deepcopy(TEST_PARAMS),
        "specFields": copy.deepcopy(SPEC_FIELDS),
        "seq": {"asset": 1, "usn": 50001, "project": 1001, "client": 1, "user": 3, "blancco": 1, "manifest": 1},
        "_rev": 0,
    }


def looks_like_demo_register(state: dict[str, Any] | None) -> bool:
    if not state or not isinstance(state, dict):
        return True
    if state.get("_schema") == SCHEMA_VERSION:
        return False
    emails = {
        str(u.get("email") or "").strip().lower()
        for u in (state.get("users") or [])
        if isinstance(u, dict)
    }
    if emails & DEMO_USER_EMAILS:
        return True
    pids = {str(p.get("id")) for p in (state.get("projects") or []) if isinstance(p, dict)}
    if pids & DEMO_PROJECT_IDS:
        return True
    assets = state.get("assets") or []
    if assets:
        return True
    clients = state.get("clients") or []
    if clients:
        return True
    return len(emails) > 2 or bool(emails - set(ALLOWED_USERS))


def _is_simulated_blancco(report: Any) -> bool:
    if not isinstance(report, dict) or not report:
        return False
    blob = " ".join(
        str(report.get(k) or "")
        for k in ("source", "software", "operator", "raw", "reportId")
    ).lower()
    return any(m in blob for m in SIMULATED_MARKERS)


def snapshot_state_bytes() -> bytes | None:
    ensure_dirs()
    with _lock:
        if not STATE_PATH.exists():
            return None
        raw = STATE_PATH.read_bytes()
    if not raw.strip():
        return None
    return raw


def replace_state_bytes(raw: bytes) -> None:
    if not raw.strip():
        raise ValueError("Backup is empty; live register was not changed.")
    json.loads(raw.decode("utf-8"))
    ensure_dirs()
    with _lock:
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_bytes(raw)
        tmp.replace(STATE_PATH)


def _read_unlocked() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    raw = STATE_PATH.read_text(encoding="utf-8")
    if not raw.strip():
        return None
    return json.loads(raw)


def _write_unlocked(state: dict[str, Any]) -> dict[str, Any]:
    state["_schema"] = SCHEMA_VERSION
    state["_rev"] = int(state.get("_rev") or 0) + 1
    state["_savedAt"] = _now()
    cfg = dict(state.get("blanccoConfig") or {})
    cfg.pop("apiKey", None)
    cfg["hasApiKey"] = bool(BLANCCO_API_KEY)
    if not cfg.get("mode") or str(cfg.get("mode", "")).lower().startswith("demo"):
        cfg["mode"] = "Live" if BLANCCO_API_KEY else "Off"
    cfg["endpoint"] = cfg.get("endpoint") or BLANCCO_ENDPOINT
    state["blanccoConfig"] = cfg
    encoded = json.dumps(state, ensure_ascii=False)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(encoded, encoding="utf-8")
    tmp.replace(STATE_PATH)
    return state


def load_state() -> dict[str, Any] | None:
    raw = snapshot_state_bytes()
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


def _strip_secrets(state: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(state)
    cfg = dict(out.get("blanccoConfig") or {})
    cfg.pop("apiKey", None)
    cfg["hasApiKey"] = bool(BLANCCO_API_KEY)
    out["blanccoConfig"] = cfg
    for user in out.get("users") or []:
        if isinstance(user, dict):
            user.pop("totpSecret", None)
            user.pop("password", None)
    return out


def assigned_project_ids(state: dict[str, Any], user: dict[str, Any]) -> set[str]:
    uid = user.get("id") or user.get("userId")
    if user.get("role") == "Super Admin":
        return {str(p.get("id")) for p in (state.get("projects") or []) if p.get("id")}
    out: set[str] = set()
    for proj in state.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        team = proj.get("team") or []
        if uid in team or proj.get("managerId") == uid:
            out.add(str(proj["id"]))
    return out


def filter_state_for_user(state: dict[str, Any] | None, user: dict[str, Any]) -> dict[str, Any]:
    if not state:
        state = empty_production_state()
    view = _strip_secrets(state)
    uid = user.get("id") or user.get("userId")
    if user.get("role") == "Super Admin":
        view["users"] = [public_user(u, include_contact=True) for u in (view.get("users") or [])]
        return view
    pids = assigned_project_ids(state, user)
    view["projects"] = [p for p in (view.get("projects") or []) if p.get("id") in pids]
    cids = {p.get("clientId") for p in view["projects"]}
    clients = []
    for client in view.get("clients") or []:
        if client.get("id") not in cids:
            continue
        clients.append(
            {
                "id": client.get("id"),
                "name": client.get("name"),
                "blanccoOptIn": bool(client.get("blanccoOptIn")),
            }
        )
    view["clients"] = clients
    view["assets"] = [a for a in (view.get("assets") or []) if a.get("projectId") in pids]
    view["manifests"] = []
    names = {}
    for u in state.get("users") or []:
        if isinstance(u, dict) and u.get("id"):
            names[u["id"]] = {"id": u["id"], "name": u.get("name"), "role": u.get("role")}
    roster = []
    for u in view.get("users") or []:
        if u.get("id") == uid:
            roster.append(public_user(u, include_contact=True))
        elif u.get("id") in names:
            roster.append(names[u["id"]])
    if not any(u.get("id") == uid for u in roster):
        roster.insert(0, public_user(account_for_id(uid) or user, include_contact=True))
    view["users"] = roster
    company = dict(view.get("company") or {})
    view["company"] = {"name": company.get("name"), "brand": company.get("brand"), "currency": company.get("currency") or "INR"}
    return view


def _next_id(seq: dict[str, Any], kind: str, prefix: str, width: int) -> str:
    n = int(seq.get(kind) or 1)
    seq[kind] = n + 1
    return f"{prefix}{str(n).zfill(width)}"


def _history_entry(user: dict[str, Any], ev: str) -> dict[str, str]:
    return {"ts": _stamp(), "by": user.get("name") or user.get("email") or user.get("id"), "ev": ev, "server": True}


def _find(rows: list, rid: str) -> dict[str, Any] | None:
    for row in rows or []:
        if isinstance(row, dict) and row.get("id") == rid:
            return row
    return None


def _replace(rows: list, record: dict[str, Any]) -> list:
    out = []
    found = False
    for row in rows or []:
        if isinstance(row, dict) and row.get("id") == record.get("id"):
            out.append(record)
            found = True
        else:
            out.append(row)
    if not found:
        out.append(record)
    return out


def _require_id(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not ID_RE.match(text):
        raise HTTPException(status_code=400, detail=f"Invalid {label}.")
    return text


def serial_taken(state: dict[str, Any], serial: str, project_id: str, except_id: str | None = None) -> bool:
    s = str(serial or "").strip().lower()
    if not s:
        return False
    noserial = bool(re.match(r"^noserial-\d+$", s))
    for asset in state.get("assets") or []:
        if except_id and asset.get("id") == except_id:
            continue
        other = str(asset.get("serial") or "").strip().lower()
        if not other:
            continue
        if noserial:
            if asset.get("projectId") == project_id and other == s:
                return True
        elif other == s and asset.get("projectId") == project_id:
            return True
        elif other == s:
            # Returning device: allowed when the other project is completed/cancelled.
            other_p = _find(state.get("projects") or [], asset.get("projectId"))
            status = (other_p or {}).get("status") or "Active"
            if status not in {"Completed", "Cancelled"}:
                return True
    return False


def _can_edit_project(user: dict[str, Any], state: dict[str, Any], project_id: str) -> bool:
    if user.get("role") == "Super Admin":
        return True
    return project_id in assigned_project_ids(state, user)


def _freeze_grade(asset: dict[str, Any]) -> None:
    if asset.get("status") == "Verified":
        asset["gradeFrozen"] = True
        asset["frozenGrade"] = asset.get("grade")
        asset["frozenGradeReason"] = asset.get("gradeReason")


def _apply_verified_lock(existing: dict[str, Any] | None, incoming: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    if not existing or existing.get("status") != "Verified":
        incoming.pop("gradeFrozen", None)
        return incoming
    reopen = incoming.get("status") in {"Registered", "In Testing", "Tested", "Rejected"}
    if user.get("role") != "Super Admin":
        raise HTTPException(status_code=403, detail="Verified assets are locked.")
    if not reopen and incoming.get("status") == "Verified":
        locked = copy.deepcopy(existing)
        # Allow remarks-only? No — stay verified, no field edits except reopen.
        raise HTTPException(
            status_code=409,
            detail="Verified assets are locked. Reopen for re-verification to edit.",
        )
    incoming["grade"] = existing.get("frozenGrade") or existing.get("grade")
    incoming["gradeReason"] = existing.get("frozenGradeReason") or existing.get("gradeReason")
    incoming["gradeFrozen"] = False
    incoming["verifiedBy"] = None
    incoming["verifiedAt"] = None
    return incoming


def _sanitize_blancco(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> None:
    """Never accept client-invented Blancco reports. Keep only server-stored API reports."""
    report = incoming.get("blancco")
    prev = (existing or {}).get("blancco")
    if report is None:
        incoming["blancco"] = prev
        return
    if report == prev:
        return
    if _is_simulated_blancco(report):
        incoming["blancco"] = prev
        return
    if prev and report.get("reportId") == prev.get("reportId") and report.get("source") == prev.get("source"):
        incoming["blancco"] = prev if prev.get("source") == "Blancco API" else report
        if incoming["blancco"] and incoming["blancco"].get("source") != "Blancco API":
            incoming["blancco"] = prev
        return
    # Client may not create or replace a report. Server lookup writes source=Blancco API.
    incoming["blancco"] = prev


def upsert_asset(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Asset must be JSON.")
    with _lock:
        state = _read_unlocked() or empty_production_state()
        seq = dict(state.get("seq") or {})
        asset_id = str(payload.get("id") or "").strip() or _next_id(seq, "asset", "AST-", 5)
        existing = _find(state.get("assets") or [], asset_id)
        project_id = str(payload.get("projectId") or (existing or {}).get("projectId") or "").strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="Project is required.")
        if not _can_edit_project(user, state, project_id):
            raise HTTPException(status_code=403, detail="That project is not assigned to you.")
        serial = str(payload.get("serial") or (existing or {}).get("serial") or "").strip()
        if not serial or not SERIAL_RE.match(serial):
            raise HTTPException(status_code=400, detail="Serial is required.")
        if serial_taken(state, serial, project_id, existing.get("id") if existing else None):
            raise HTTPException(status_code=409, detail="Serial already exists on an active project.")
        usn = str(payload.get("usn") or (existing or {}).get("usn") or "").strip()
        if not usn:
            usn = _next_id(seq, "usn", "URB-", 6)
        status = str(payload.get("status") or (existing or {}).get("status") or "Registered")
        if status not in ASSET_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status.")
        if user.get("role") != "Super Admin" and status == "Verified":
            status = "Tested"
        incoming = copy.deepcopy(existing) if existing else {}
        incoming.update(payload)
        incoming["id"] = asset_id
        incoming["projectId"] = project_id
        incoming["serial"] = serial
        incoming["usn"] = usn
        incoming["status"] = status
        incoming["category"] = str(incoming.get("category") or "Laptop")[:40]
        incoming["brand"] = str(incoming.get("brand") or "—")[:80]
        incoming["model"] = str(incoming.get("model") or "—")[:80]
        incoming["remarks"] = str(incoming.get("remarks") or "")[:500]
        incoming["rejectNote"] = str(incoming.get("rejectNote") or "")[:500]
        if not isinstance(incoming.get("tests"), dict):
            incoming["tests"] = {}
        if not isinstance(incoming.get("measures"), dict):
            incoming["measures"] = {}
        if not isinstance(incoming.get("specs"), dict):
            incoming["specs"] = {}
        if user.get("role") != "Super Admin":
            incoming["testedBy"] = incoming.get("testedBy") or user.get("id")
            incoming["verifiedBy"] = (existing or {}).get("verifiedBy")
            incoming["verifiedAt"] = (existing or {}).get("verifiedAt")
        incoming = _apply_verified_lock(existing, incoming, user)
        _sanitize_blancco(existing, incoming)
        if incoming.get("status") == "Verified":
            _freeze_grade(incoming)
        history = list(incoming.get("history") or [])
        ev = "Updated" if existing else "Registered"
        history.append(_history_entry(user, ev + " " + serial))
        incoming["history"] = history[-80:]
        incoming["_updatedAt"] = _now()
        state["assets"] = _replace(state.get("assets") or [], incoming)
        state["seq"] = seq
        saved = _write_unlocked(state)
    append_audit(user, "asset.upsert", "asset", asset_id, incoming.get("serial", ""))
    return incoming | {"_rev": saved["_rev"]}


def upsert_client(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") != "Super Admin":
        raise HTTPException(status_code=403, detail="Super Admin only.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Client must be JSON.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Client name is required.")
    with _lock:
        state = _read_unlocked() or empty_production_state()
        seq = dict(state.get("seq") or {})
        cid = str(payload.get("id") or "").strip() or _next_id(seq, "client", "CL-", 1)
        existing = _find(state.get("clients") or [], cid) or {}
        row = dict(existing)
        row.update(
            {
                "id": cid,
                "name": name[:120],
                "gstin": str(payload.get("gstin") or row.get("gstin") or "")[:20],
                "pan": str(payload.get("pan") or row.get("pan") or "")[:20],
                "contact": str(payload.get("contact") or row.get("contact") or "")[:80],
                "phone": str(payload.get("phone") or row.get("phone") or "")[:40],
                "email": str(payload.get("email") or row.get("email") or "")[:120],
                "address": str(payload.get("address") or row.get("address") or "")[:200],
                "blanccoOptIn": bool(payload["blanccoOptIn"]) if "blanccoOptIn" in payload else bool(row.get("blanccoOptIn")),
            }
        )
        state["clients"] = _replace(state.get("clients") or [], row)
        state["seq"] = seq
        saved = _write_unlocked(state)
    append_audit(user, "client.upsert", "client", cid, name)
    return row | {"_rev": saved["_rev"]}


def upsert_project(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") != "Super Admin":
        raise HTTPException(status_code=403, detail="Super Admin only.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Project must be JSON.")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required.")
    with _lock:
        state = _read_unlocked() or empty_production_state()
        seq = dict(state.get("seq") or {})
        pid = str(payload.get("id") or "").strip() or _next_id(seq, "project", "PRJ-", 4)
        existing = _find(state.get("projects") or [], pid) or {}
        row = dict(existing)
        team = payload.get("team") if isinstance(payload.get("team"), list) else existing.get("team") or []
        team = [str(t) for t in team if str(t) in {u["id"] for u in ALLOWED_USERS.values()}]
        row.update(
            {
                "id": pid,
                "name": name[:160],
                "clientId": str(payload.get("clientId") or row.get("clientId") or "")[:20],
                "site": str(payload.get("site") or row.get("site") or "")[:160],
                "mode": str(payload.get("mode") or row.get("mode") or "")[:80],
                "start": str(payload.get("start") or row.get("start") or "")[:12],
                "due": str(payload.get("due") or row.get("due") or "")[:12],
                "status": str(payload.get("status") or row.get("status") or "Active")[:40],
                "managerId": str(payload.get("managerId") or row.get("managerId") or "U-1")[:20],
                "team": team,
                "scope": payload.get("scope") if isinstance(payload.get("scope"), list) else row.get("scope") or [],
                "notes": str(payload.get("notes") or row.get("notes") or "")[:2000],
            }
        )
        state["projects"] = _replace(state.get("projects") or [], row)
        state["seq"] = seq
        saved = _write_unlocked(state)
    append_audit(user, "project.upsert", "project", pid, name)
    return row | {"_rev": saved["_rev"]}


def upsert_company(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") != "Super Admin":
        raise HTTPException(status_code=403, detail="Super Admin only.")
    with _lock:
        state = _read_unlocked() or empty_production_state()
        company = dict(state.get("company") or {})
        if payload.get("name") is not None:
            company["name"] = str(payload.get("name") or "")[:160]
        if payload.get("brand") is not None:
            company["brand"] = str(payload.get("brand") or "")[:80]
        if payload.get("gstin") is not None:
            company["gstin"] = str(payload.get("gstin") or "")[:20]
        company["currency"] = "INR"
        state["company"] = company
        saved = _write_unlocked(state)
    append_audit(user, "company.update", "company", "company", company.get("name", ""))
    return company | {"_rev": saved["_rev"]}


def upsert_config(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") != "Super Admin":
        raise HTTPException(status_code=403, detail="Super Admin only.")
    with _lock:
        state = _read_unlocked() or empty_production_state()
        if "categories" in payload and isinstance(payload["categories"], list):
            state["categories"] = [str(c)[:40] for c in payload["categories"] if str(c).strip()]
        if "testParams" in payload and isinstance(payload["testParams"], dict):
            state["testParams"] = payload["testParams"]
        if "specFields" in payload and isinstance(payload["specFields"], dict):
            state["specFields"] = payload["specFields"]
        if "blanccoCategories" in payload and isinstance(payload["blanccoCategories"], list):
            state["blanccoCategories"] = [str(c)[:40] for c in payload["blanccoCategories"]]
        if "blanccoConfig" in payload and isinstance(payload["blanccoConfig"], dict):
            cfg = dict(state.get("blanccoConfig") or {})
            incoming = dict(payload["blanccoConfig"])
            incoming.pop("apiKey", None)
            if incoming.get("endpoint"):
                cfg["endpoint"] = str(incoming["endpoint"])[:300]
            if incoming.get("mode") in {"Live", "Off"}:
                cfg["mode"] = incoming["mode"]
            elif str(incoming.get("mode") or "").lower().startswith("demo"):
                cfg["mode"] = "Live" if BLANCCO_API_KEY else "Off"
            if "autoFetch" in incoming:
                cfg["autoFetch"] = bool(incoming["autoFetch"])
            if incoming.get("lastSync"):
                cfg["lastSync"] = str(incoming["lastSync"])[:40]
            cfg.pop("apiKey", None)
            cfg["hasApiKey"] = bool(BLANCCO_API_KEY)
            state["blanccoConfig"] = cfg
        saved = _write_unlocked(state)
    append_audit(user, "config.update", "config", "config", "")
    return {
        "categories": saved.get("categories"),
        "testParams": saved.get("testParams"),
        "specFields": saved.get("specFields"),
        "blanccoCategories": saved.get("blanccoCategories"),
        "blanccoConfig": _strip_secrets(saved)["blanccoConfig"],
        "_rev": saved["_rev"],
    }


def upsert_user_profile(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") != "Super Admin":
        raise HTTPException(status_code=403, detail="Super Admin only.")
    uid = str(payload.get("id") or "").strip()
    account = account_for_id(uid)
    if not account:
        raise HTTPException(status_code=400, detail="Only the two production accounts exist.")
    with _lock:
        state = _read_unlocked() or empty_production_state()
        existing = _find(state.get("users") or [], uid) or dict(account)
        name = str(payload.get("name") or existing.get("name") or account["name"])[:80]
        phone = str(payload.get("phone") if payload.get("phone") is not None else existing.get("phone") or "")[:40]
        active = existing.get("active", True)
        if "active" in payload and uid != user.get("id"):
            active = bool(payload["active"])
        row = {
            **existing,
            **account,
            "name": name,
            "phone": phone,
            "active": active,
            "email": account["email"],
            "role": account["role"],
            "id": uid,
        }
        state["users"] = _replace(state.get("users") or [], row)
        saved = _write_unlocked(state)
    append_audit(user, "user.update", "user", uid, name)
    return public_user(row) | {"_rev": saved["_rev"]}


def add_manifest(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") != "Super Admin":
        raise HTTPException(status_code=403, detail="Super Admin only.")
    project_id = str(payload.get("projectId") or "").strip()
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    if not project_id or not rows:
        raise HTTPException(status_code=400, detail="Manifest needs a project and rows.")
    with _lock:
        state = _read_unlocked() or empty_production_state()
        seq = dict(state.get("seq") or {})
        mid = str(payload.get("id") or "").strip() or _next_id(seq, "manifest", "MF-", 1)
        row = {
            "id": mid,
            "projectId": project_id,
            "uploaded": _now()[:10],
            "by": user.get("id"),
            "file": str(payload.get("file") or "manifest.csv")[:120],
            "rows": [
                {
                    "serial": str(r.get("serial") or "")[:80],
                    "category": str(r.get("category") or "")[:40],
                    "brand": str(r.get("brand") or "")[:80],
                    "model": str(r.get("model") or "")[:80],
                }
                for r in rows
                if isinstance(r, dict) and r.get("serial")
            ],
        }
        manifests = list(state.get("manifests") or [])
        manifests.append(row)
        state["manifests"] = manifests[-50:]
        state["seq"] = seq
        saved = _write_unlocked(state)
    append_audit(user, "manifest.add", "manifest", mid, project_id)
    return row | {"_rev": saved["_rev"]}


def import_assets(user: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    added: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        body = dict(raw)
        body.pop("blancco", None)
        body["blancco"] = None
        body["testedBy"] = user.get("id")
        if user.get("role") != "Super Admin" and body.get("status") == "Verified":
            body["status"] = "Tested"
        try:
            saved = upsert_asset(user, body)
            added.append(saved.get("id") or "")
        except HTTPException as exc:
            if exc.status_code == 409:
                skipped.append(str(body.get("serial") or ""))
            else:
                errors.append(str(exc.detail))
    return {"added": len(added), "skipped": len(skipped), "errors": errors, "ids": added}


def attach_blancco_report(user: dict[str, Any], asset_id: str, report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict) or not report.get("reportId"):
        raise HTTPException(status_code=400, detail="Not a Blancco API report.")
    if _is_simulated_blancco(report):
        raise HTTPException(status_code=400, detail="Simulated Blancco reports are not stored.")
    report = dict(report)
    report["source"] = "Blancco API"
    with _lock:
        state = _read_unlocked() or empty_production_state()
        existing = _find(state.get("assets") or [], asset_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Asset not found.")
        if not _can_edit_project(user, state, existing.get("projectId")):
            raise HTTPException(status_code=403, detail="That project is not assigned to you.")
        existing = dict(existing)
        existing["blancco"] = report
        history = list(existing.get("history") or [])
        history.append(_history_entry(user, "Blancco report " + str(report.get("reportId")) + " linked"))
        existing["history"] = history[-80:]
        existing["_updatedAt"] = _now()
        state["assets"] = _replace(state.get("assets") or [], existing)
        saved = _write_unlocked(state)
    append_audit(user, "blancco.link", "asset", asset_id, str(report.get("reportId")))
    return existing | {"_rev": saved["_rev"]}


def apply_sync(user: dict[str, Any], upserts: dict[str, Any]) -> dict[str, Any]:
    """Apply per-record upserts. Not a whole-DB replace."""
    if not isinstance(upserts, dict):
        raise HTTPException(status_code=400, detail="Sync body is invalid.")
    last: dict[str, Any] = {}
    for asset in upserts.get("assets") or []:
        last = upsert_asset(user, asset)
    if user.get("role") == "Super Admin":
        for client in upserts.get("clients") or []:
            last = upsert_client(user, client)
        for project in upserts.get("projects") or []:
            last = upsert_project(user, project)
        if upserts.get("company"):
            last = upsert_company(user, upserts["company"])
        config_keys = ("categories", "testParams", "specFields", "blanccoConfig", "blanccoCategories")
        if any(k in upserts for k in config_keys):
            last = upsert_config(user, {k: upserts[k] for k in config_keys if k in upserts})
        for person in upserts.get("users") or []:
            last = upsert_user_profile(user, person)
        for manifest in upserts.get("manifests") or []:
            last = add_manifest(user, manifest)
    state = load_state() or empty_production_state()
    return {"ok": True, "_rev": state.get("_rev"), "state": filter_state_for_user(state, user), "last": last}


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    """Internal/test helper. Production HTTP no longer accepts whole-DB PUT."""
    if not isinstance(state, dict):
        raise TypeError("State must be JSON.")
    missing = [k for k in REQUIRED if k not in state]
    if missing:
        raise ValueError("State is missing: " + ", ".join(missing))
    ensure_dirs()
    with _lock:
        current = _read_unlocked()
        if current and int(state.get("_rev") or 0) < int(current.get("_rev") or 0):
            raise StaleState(current)
        if current:
            state["_rev"] = int(current.get("_rev") or 0)
        else:
            state["_rev"] = 0
        return _write_unlocked(state)


def write_empty_production(actor: dict[str, Any] | None = None, reason: str = "cutover") -> dict[str, Any]:
    ensure_dirs()
    state = empty_production_state()
    with _lock:
        saved = _write_unlocked(state)
        _cutover_marker().write_text(_now() + " " + reason + "\n", encoding="utf-8")
    append_audit(actor or {"id": "system", "name": "system", "role": "system"}, "register.wipe", "register", "", reason)
    return saved


def cutover_if_needed() -> dict[str, Any]:
    """One-shot production wipe of historical/demo register data."""
    ensure_dirs()
    marker = _cutover_marker()
    current = load_state()
    if marker.exists() and current and current.get("_schema") == SCHEMA_VERSION:
        with _lock:
            current = _read_unlocked() or empty_production_state()
            changed = False
            users = []
            allowed_ids = {u["id"] for u in ALLOWED_USERS.values()}
            by_id = {u["id"]: copy.deepcopy(u) for u in ALLOWED_USERS.values()}
            for row in current.get("users") or []:
                if isinstance(row, dict) and row.get("id") in allowed_ids:
                    base = by_id[row["id"]]
                    base["name"] = row.get("name") or base["name"]
                    base["phone"] = row.get("phone") or ""
                    base["active"] = row.get("active", True)
                    users.append(base)
                    del by_id[row["id"]]
            users.extend(by_id.values())
            if [u["id"] for u in users] != [u.get("id") for u in (current.get("users") or [])]:
                current["users"] = users
                changed = True
            cleaned_assets = []
            for asset in current.get("assets") or []:
                if not isinstance(asset, dict):
                    continue
                if _is_simulated_blancco(asset.get("blancco")):
                    asset = dict(asset)
                    asset["blancco"] = None
                    changed = True
                cleaned_assets.append(asset)
            current["assets"] = cleaned_assets
            cfg = dict(current.get("blanccoConfig") or {})
            if cfg.get("apiKey"):
                cfg.pop("apiKey", None)
                changed = True
            current["blanccoConfig"] = cfg
            if changed:
                current = _write_unlocked(current)
            return current
    if current:
        try:
            from app.backup import run_backup

            run_backup()
        except Exception:
            pass
    return write_empty_production(
        reason="production cutover: empty register except manish@urbeno.in and darshak@urbeno.in"
    )

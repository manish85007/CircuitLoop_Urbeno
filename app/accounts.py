"""Seed accounts. Super Admin can add more users on the register."""
from __future__ import annotations

import re
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]{1,80}@[^@\s]{1,80}\.[^@\s]{1,24}$")

# Built-in accounts always exist. Super Admin may add more from Users.
ALLOWED_USERS: dict[str, dict[str, Any]] = {
    "manish@urbeno.in": {
        "id": "U-1",
        "name": "Manish Kumar",
        "email": "manish@urbeno.in",
        "role": "Super Admin",
        "phone": "",
        "active": True,
    },
    "darshak@urbeno.in": {
        "id": "U-2",
        "name": "Darshak",
        "email": "darshak@urbeno.in",
        "role": "Field Engineer",
        "phone": "",
        "active": True,
    },
}

ALLOWED_EMAILS = frozenset(ALLOWED_USERS)
SEED_USER_IDS = frozenset(row["id"] for row in ALLOWED_USERS.values())
ADMIN_EMAIL = "manish@urbeno.in"
FIELD_EMAIL = "darshak@urbeno.in"
ADMIN_ID = "U-1"


def normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def valid_login_email(value: str | None) -> str:
    addr = normalize_email(value)
    if not addr or not EMAIL_RE.match(addr) or len(addr) > 120:
        return ""
    return addr


def is_seed_user(user_id: str | None = None, email: str | None = None) -> bool:
    if user_id and str(user_id) in SEED_USER_IDS:
        return True
    return normalize_email(email) in ALLOWED_USERS


def account_for_email(email: str | None) -> dict[str, Any] | None:
    row = ALLOWED_USERS.get(normalize_email(email))
    return dict(row) if row else None


def account_for_id(user_id: str | None) -> dict[str, Any] | None:
    for row in ALLOWED_USERS.values():
        if row["id"] == user_id:
            return dict(row)
    return None


def public_user(row: dict[str, Any], *, include_contact: bool = True) -> dict[str, Any]:
    role = str(row.get("role") or "").strip()
    compact = " ".join(role.split()).lower().replace(" ", "")
    if compact == "superadmin":
        role = "Super Admin"
    elif compact == "leadengineer":
        role = "Lead Engineer"
    elif compact == "fieldengineer":
        role = "Field Engineer"
    out = {
        "id": row.get("id"),
        "name": row.get("name"),
        "role": role or "Field Engineer",
        "active": row.get("active", True),
    }
    if include_contact:
        out["email"] = row.get("email")
        out["phone"] = row.get("phone") or ""
    return out

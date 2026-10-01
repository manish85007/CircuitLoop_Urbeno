"""Production accounts. Roles are server-side; the browser cannot pick them."""
from __future__ import annotations

from typing import Any

# Login is restricted to these two emails. Roles are not client-controlled.
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
ADMIN_EMAIL = "manish@urbeno.in"
FIELD_EMAIL = "darshak@urbeno.in"


def normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def account_for_email(email: str | None) -> dict[str, Any] | None:
    row = ALLOWED_USERS.get(normalize_email(email))
    return dict(row) if row else None


def account_for_id(user_id: str | None) -> dict[str, Any] | None:
    for row in ALLOWED_USERS.values():
        if row["id"] == user_id:
            return dict(row)
    return None


def public_user(row: dict[str, Any], *, include_contact: bool = True) -> dict[str, Any]:
    out = {
        "id": row.get("id"),
        "name": row.get("name"),
        "role": row.get("role"),
        "active": row.get("active", True),
    }
    if include_contact:
        out["email"] = row.get("email")
        out["phone"] = row.get("phone") or ""
    return out

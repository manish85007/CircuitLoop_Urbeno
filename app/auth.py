from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import COOKIE_NAME, SESSION_HOURS, SESSION_SECRET

serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="circuitloop-field")


def issue_session(response: Response, user: dict) -> None:
    token = serializer.dumps(
        {
            "userId": user["id"],
            "name": user["name"],
            "role": user["role"],
            "iat": datetime.now(timezone.utc).isoformat(),
        }
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def read_session(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        return serializer.loads(token, max_age=SESSION_HOURS * 3600)
    except (BadSignature, SignatureExpired):
        return None


def require_user(request: Request) -> dict:
    session = read_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return session

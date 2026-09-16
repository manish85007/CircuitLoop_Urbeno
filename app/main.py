from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import clear_session, issue_session, read_session
from app.blancco import lookup as blancco_lookup
from app.config import APP_NAME, BRAND, CORS_ORIGINS, DATA_DIR, ROOT, STATE_PATH, ensure_dirs
from app.store import StaleState, load_state, save_state

STATIC_DIR = ROOT / "static"
NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


def api_json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers=NO_STORE)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_dirs()
    yield


app = FastAPI(title=f"{APP_NAME} field API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if CORS_ORIGINS == "*" else [o.strip() for o in CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SessionIn(BaseModel):
    userId: str = Field(min_length=1, max_length=40)


class BlanccoIn(BaseModel):
    serial: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)


def _user_from_state(user_id: str) -> dict[str, Any] | None:
    state = load_state()
    if not state:
        return None
    for user in state.get("users") or []:
        if user.get("id") == user_id:
            return user
    return None


@app.get("/api/health")
def health() -> JSONResponse:
    return api_json(
        {
            "ok": True,
            "app": APP_NAME,
            "brand": BRAND,
            "persist": {
                "dataDir": str(DATA_DIR),
                "statePath": str(STATE_PATH),
                "hasState": STATE_PATH.exists() and STATE_PATH.stat().st_size > 0,
            },
        }
    )


@app.get("/api/state")
def get_state() -> JSONResponse:
    return api_json({"state": load_state()})


@app.put("/api/state")
def put_state(payload: dict[str, Any]) -> JSONResponse:
    body = payload.get("state", payload)
    try:
        saved = save_state(body)
    except StaleState as exc:
        return api_json({"error": str(exc), "state": exc.current}, 409)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TypeError as exc:
        raise HTTPException(status_code=400, detail="State must be JSON.") from exc
    return api_json({"ok": True, "state": saved})


@app.post("/api/session")
def create_session(body: SessionIn, response: Response) -> dict[str, Any]:
    user = _user_from_state(body.userId)
    if user is None:
        # First sign-in happens before the seed has been POSTed; accept the id
        # and let the next /api/state persist the roster.
        user = {"id": body.userId, "name": body.userId, "role": "Field Engineer", "active": True}
    if user.get("active") is False:
        raise HTTPException(status_code=401, detail="That user is disabled.")
    issue_session(response, user)
    return {"user": {"id": user["id"], "name": user.get("name"), "role": user.get("role")}}


@app.get("/api/session")
def read_current_session(request: Request) -> dict[str, Any]:
    session = read_session(request)
    if not session:
        return {"user": None}
    user = _user_from_state(session["userId"])
    if user:
        return {"user": {"id": user["id"], "name": user["name"], "role": user["role"]}}
    return {
        "user": {
            "id": session["userId"],
            "name": session.get("name"),
            "role": session.get("role"),
        }
    }


@app.delete("/api/session")
def sign_out(response: Response) -> dict[str, Any]:
    clear_session(response)
    return {"ok": True}


@app.post("/api/blancco/lookup")
async def blancco(body: BlanccoIn) -> dict[str, Any]:
    state = load_state() or {}
    cfg = state.get("blanccoConfig") or {}
    return await blancco_lookup(body.serial, body.category, cfg)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse({"error": detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = first.get("loc", ["body"])[-1]
    return JSONResponse({"error": f"Check the {loc} field and try again."}, status_code=422)


@app.get("/static/persist.js")
def persist_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "persist.js", media_type="text/javascript", headers=NO_STORE)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=NO_STORE)

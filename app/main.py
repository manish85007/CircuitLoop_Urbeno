from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from app.audit import recent_audit
from app.auth import (
    discard_invalid_session_cookie,
    end_session,
    issue_session,
    read_session,
    require_admin,
    require_user,
    signed_out_blocked,
    start_login,
    verify_login,
)
from app.backup import backup_loop, public_backup_status
from app.blancco import lookup as blancco_lookup
from app.config import (
    APP_NAME,
    BRAND,
    ROOT,
    cors_origin_list,
    email_delivery_public,
    email_otp_enabled,
    ensure_dirs,
    preview_login_enabled,
)
from app.store import (
    add_manifest,
    attach_blancco_report,
    apply_sync,
    cutover_if_needed,
    empty_production_state,
    filter_state_for_user,
    import_assets,
    load_state,
    seed_preview_register,
    upsert_asset,
    upsert_client,
    upsert_company,
    upsert_config,
    upsert_project,
    upsert_user_profile,
)

STATIC_DIR = ROOT / "static"
NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}

PUBLIC_API = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/start"),
    ("POST", "/api/auth/verify"),
    ("POST", "/api/auth/otp"),
    ("POST", "/api/login"),
    ("POST", "/api/otp"),
    ("POST", "/api/session"),
    ("POST", "/api/preview/login"),
}

CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com data:; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Permitted-Cross-Domain-Policies": "none",
}


def api_json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers=NO_STORE)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


class AuthGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        if path.startswith("/api/") and (method, path) not in PUBLIC_API:
            if path == "/api/session" and method in {"GET", "DELETE"}:
                return await call_next(request)
            if path == "/api/assets/import-template.csv" and method == "GET":
                session = read_session(request)
                if not session:
                    payload = api_json({"error": "Sign in to continue."}, 401)
                    discard_invalid_session_cookie(request, payload)
                    return payload
                return await call_next(request)
            session = read_session(request)
            if not session:
                payload = api_json({"error": "Sign in to continue."}, 401)
                discard_invalid_session_cookie(request, payload)
                return payload
            request.state.user = session
        return await call_next(request)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_dirs()
    cutover_if_needed()
    seed_preview_register()
    task = None
    from app.config import backup_enabled

    if backup_enabled():
        task = asyncio.create_task(backup_loop(), name="circuitloop-backup")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title=f"{APP_NAME} field API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
origins = cors_origin_list()
app.add_middleware(AuthGateMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["https://loop.urbeno.in"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
)
app.add_middleware(SecurityHeadersMiddleware)


class EmailIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    bootstrapToken: str = ""
    method: str = ""


class VerifyIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    code: str = Field(min_length=6, max_length=8)
    bootstrapToken: str = ""


class BlanccoIn(BaseModel):
    serial: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)
    assetId: str = ""


class SyncIn(BaseModel):
    upserts: dict[str, Any] = Field(default_factory=dict)


@app.get("/api/health")
def health() -> JSONResponse:
    state = load_state()
    return api_json(
        {
            "ok": True,
            "app": APP_NAME,
            "brand": BRAND,
            "persist": {"ready": bool(state)},
            "backup": public_backup_status(),
            "emailOtp": email_otp_enabled(),
            "emailDelivery": email_delivery_public(),
            "previewLogin": preview_login_enabled(),
        }
    )


@app.post("/api/auth/start")
@app.post("/api/login")
def auth_start(body: EmailIn) -> JSONResponse:
    return api_json(start_login(body.email, body.bootstrapToken, body.method))


@app.post("/api/auth/verify")
@app.post("/api/auth/otp")
@app.post("/api/otp")
def auth_verify(body: VerifyIn) -> JSONResponse:
    user = verify_login(body.email, body.code, body.bootstrapToken)
    payload = api_json({"ok": True, "user": user})
    issue_session(payload, user)
    return payload


@app.get("/api/session")
def read_current_session(request: Request) -> JSONResponse:
    session = read_session(request)
    if not session:
        payload = api_json({"user": None})
        discard_invalid_session_cookie(request, payload)
        return payload
    return api_json(
        {
            "user": {
                "id": session["id"],
                "name": session["name"],
                "email": session["email"],
                "role": session["role"],
            }
        }
    )


@app.delete("/api/session")
def sign_out(request: Request) -> JSONResponse:
    payload = api_json({"ok": True})
    end_session(request, payload)
    return payload


@app.post("/api/preview/login")
def preview_login(request: Request) -> JSONResponse:
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if not preview_login_enabled() or host not in {"127.0.0.1", "localhost", "testserver"}:
        return api_json({"error": "Not found."}, 404)
    if signed_out_blocked(request):
        payload = api_json({"error": "Signed out. Sign in with email.", "user": None}, 401)
        return payload
    from app.accounts import ADMIN_EMAIL, account_for_email, public_user

    account = account_for_email(ADMIN_EMAIL)
    if not account:
        return api_json({"error": "Not found."}, 404)
    user = public_user(account, include_contact=True)
    payload = api_json({"ok": True, "user": user})
    issue_session(payload, account)
    return payload


@app.post("/api/session")
def reject_click_login() -> JSONResponse:
    return api_json({"error": "Sign in with email and authenticator (or email OTP)."}, 401)


@app.get("/api/state")
def get_state(request: Request) -> JSONResponse:
    user = require_user(request)
    state = load_state() or empty_production_state()
    return api_json({"state": filter_state_for_user(state, user)})


@app.put("/api/state")
def reject_whole_db_put() -> JSONResponse:
    return api_json(
        {
            "error": "Whole-register PUT is disabled. Use /api/assets, /api/clients, /api/projects, or /api/sync."
        },
        405,
    )


@app.post("/api/sync")
def sync_records(request: Request, body: SyncIn) -> JSONResponse:
    user = require_user(request)
    try:
        result = apply_sync(user, body.upserts)
    except HTTPException as exc:
        if exc.status_code == 409:
            state = load_state() or empty_production_state()
            return api_json(
                {
                    "error": str(exc.detail),
                    "notSaved": True,
                    "state": filter_state_for_user(state, user),
                },
                409,
            )
        raise
    return api_json(result)


@app.post("/api/assets")
def create_asset(request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    return api_json({"asset": upsert_asset(user, payload)})


@app.put("/api/assets/{asset_id}")
def update_asset(asset_id: str, request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    payload = dict(payload)
    payload["id"] = asset_id
    return api_json({"asset": upsert_asset(user, payload)})


@app.post("/api/assets/import")
def import_asset_rows(request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    rows = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="assets[] is required.")
    return api_json(import_assets(user, rows))


@app.post("/api/clients")
def create_client(request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    return api_json({"client": upsert_client(user, payload)})


@app.put("/api/clients/{client_id}")
def update_client(client_id: str, request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    payload = dict(payload)
    payload["id"] = client_id
    return api_json({"client": upsert_client(user, payload)})


@app.post("/api/projects")
def create_project(request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    return api_json({"project": upsert_project(user, payload)})


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    payload = dict(payload)
    payload["id"] = project_id
    return api_json({"project": upsert_project(user, payload)})


@app.put("/api/company")
def update_company(request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    return api_json({"company": upsert_company(user, payload)})


@app.put("/api/config")
def update_config(request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    return api_json(upsert_config(user, payload))


@app.post("/api/users")
def create_user(request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_admin(request)
    created = upsert_user_profile(user, dict(payload or {}))
    state = load_state() or empty_production_state()
    return api_json({"user": created, "state": filter_state_for_user(state, user)})


@app.put("/api/users/{user_id}")
def update_user(user_id: str, request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    payload = dict(payload)
    payload["id"] = user_id
    saved = upsert_user_profile(user, payload)
    state = load_state() or empty_production_state()
    return api_json({"user": saved, "state": filter_state_for_user(state, user)})


@app.post("/api/manifests")
def create_manifest(request: Request, payload: dict[str, Any]) -> JSONResponse:
    user = require_user(request)
    return api_json({"manifest": add_manifest(user, payload)})


@app.get("/api/audit")
def get_audit(request: Request) -> JSONResponse:
    require_admin(request)
    return api_json({"events": recent_audit(300)})


@app.post("/api/blancco/lookup")
async def blancco(request: Request, body: BlanccoIn) -> JSONResponse:
    user = require_user(request)
    result = await blancco_lookup(body.serial, body.category)
    if result.get("ok") and body.assetId:
        attach_blancco_report(user, body.assetId, result["report"])
    return api_json(result)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse({"error": detail}, status_code=exc.status_code, headers=NO_STORE)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = first.get("loc", ["body"])[-1]
    return JSONResponse(
        {"error": f"Check the {loc} field and try again."},
        status_code=422,
        headers=NO_STORE,
    )


@app.get("/docs")
@app.get("/redoc")
@app.get("/openapi.json")
def closed_docs() -> JSONResponse:
    return api_json({"error": "Not found."}, 404)


@app.get("/static/field.js")
def field_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "field.js", media_type="text/javascript", headers=NO_STORE)


@app.get("/static/persist.js")
def persist_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "persist.js", media_type="text/javascript", headers=NO_STORE)


@app.get("/static/qrcode.min.js")
def qrcode_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "qrcode.min.js", media_type="text/javascript", headers=NO_STORE)


@app.get("/static/asset-csv.js")
def asset_csv_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "asset-csv.js", media_type="text/javascript", headers=NO_STORE)


@app.get("/api/assets/import-template.csv")
def asset_import_template() -> FileResponse:
    path = STATIC_DIR / "circuitloop_asset_import_template.csv"
    return FileResponse(
        path,
        media_type="text/csv; charset=utf-8",
        headers={
            **NO_STORE,
            "Content-Disposition": 'attachment; filename="circuitloop_asset_import_template.csv"',
        },
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=NO_STORE)


@app.get("/robots.txt")
def robots() -> PlainTextResponse:
    return PlainTextResponse("User-agent: *\nDisallow: /\n", headers=NO_STORE)

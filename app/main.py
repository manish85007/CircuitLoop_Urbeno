from __future__ import annotations

import base64
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import clear_session, issue_session, read_session, require_crew
from app.config import APP_NAME, BRAND, CORS_ORIGINS, MEDIA_DIR, ROOT, ensure_dirs
from app.db import add_event, get_db, init_db, job_detail, job_summary, now_iso, pin_hash

ALLOWED_TRANSITIONS = {
    "scheduled": {"en_route", "on_site"},
    "en_route": {"on_site"},
    "on_site": {"complete"},
    "complete": set(),
}

STATIC_DIR = ROOT / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_dirs()
    init_db()
    yield


app = FastAPI(title=f"{APP_NAME} field API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if CORS_ORIGINS == "*" else [o.strip() for o in CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SessionIn(BaseModel):
    crewName: str = Field(min_length=1, max_length=80)
    pin: str = Field(min_length=4, max_length=12)


class CheckInIn(BaseModel):
    lat: float | None = None
    lng: float | None = None
    accuracy: float | None = None
    reason: str = ""


class AssetIn(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    serialNumber: str = ""
    assetTag: str = ""
    manufacturer: str = ""
    model: str = ""
    condition: str = "used"
    dataBearing: bool = False
    destructionMethod: str = "recycle"
    notes: str = ""


class SealIn(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    location: str = ""


class AcknowledgeIn(BaseModel):
    signerName: str = Field(min_length=1, max_length=80)
    signerRole: str = ""
    signatureDataUrl: str = Field(min_length=20)


class CompleteIn(BaseModel):
    overrideNote: str = ""


Db = Annotated[sqlite3.Connection, Depends(get_db)]
Crew = Annotated[dict, Depends(require_crew)]


def _job_or_404(conn: sqlite3.Connection, job_id: int) -> dict[str, Any]:
    data = job_detail(conn, job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Job not found.")
    return data


def _set_status(conn: sqlite3.Connection, job: dict[str, Any], new_status: str) -> None:
    current = job["status"]
    if new_status == current:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move {current} → {new_status}.",
        )
    conn.execute(
        "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, now_iso(), job["id"]),
    )


def _save_data_url(data_url: str, prefix: str) -> str:
    match = re.match(r"data:(image/(?:png|jpeg|jpg|webp));base64,(.+)", data_url, re.I | re.S)
    if not match:
        raise HTTPException(status_code=400, detail="Signature must be a PNG or JPEG data URL.")
    ext = "png" if "png" in match.group(1).lower() else "jpg"
    raw = base64.b64decode(match.group(2))
    if len(raw) > 1_500_000:
        raise HTTPException(status_code=400, detail="Image is too large.")
    name = f"{prefix}-{uuid.uuid4().hex}.{ext}"
    path = MEDIA_DIR / name
    path.write_bytes(raw)
    return name


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "app": APP_NAME,
        "brand": BRAND,
        "time": now_iso(),
    }


@app.post("/api/session")
def create_session(body: SessionIn, response: Response, conn: Db) -> dict[str, Any]:
    name = body.crewName.strip()
    crew = conn.execute(
        "SELECT id, name, role, pin_hash FROM crews WHERE name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()
    if crew is None or crew["pin_hash"] != pin_hash(body.pin):
        raise HTTPException(status_code=401, detail="Name or PIN is wrong.")
    payload = {"id": crew["id"], "name": crew["name"], "role": crew["role"]}
    issue_session(response, payload)
    add_event(conn, kind="session", job_id=None, crew_id=crew["id"], payload={"action": "sign_in"})
    return {"crew": payload}


@app.get("/api/session")
def get_session(request: Request, conn: Db) -> dict[str, Any]:
    session = read_session(request)
    if not session:
        return {"crew": None}
    crew = conn.execute(
        "SELECT id, name, role FROM crews WHERE id = ?",
        (session["crewId"],),
    ).fetchone()
    if crew is None:
        return {"crew": None}
    return {"crew": {"id": crew["id"], "name": crew["name"], "role": crew["role"]}}


@app.delete("/api/session")
def sign_out(request: Request, response: Response, conn: Db) -> dict[str, Any]:
    session = read_session(request)
    if session:
        add_event(conn, kind="session", job_id=None, crew_id=session.get("crewId"), payload={"action": "sign_out"})
    clear_session(response)
    return {"ok": True}


@app.get("/api/jobs")
def list_jobs(crew: Crew, conn: Db, tab: str = "today") -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY window_start ASC, id ASC"
    ).fetchall()
    jobs = [job_summary(conn, row) for row in rows]
    if tab == "done":
        jobs = [j for j in jobs if j["status"] == "complete"]
    else:
        jobs = [j for j in jobs if j["status"] != "complete"]
    return {"jobs": jobs, "tab": tab, "crew": crew}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, crew: Crew, conn: Db) -> dict[str, Any]:
    return {"job": _job_or_404(conn, job_id), "crew": crew}


@app.post("/api/jobs/{job_id}/start-route")
def start_route(job_id: int, crew: Crew, conn: Db) -> dict[str, Any]:
    job = _job_or_404(conn, job_id)
    _set_status(conn, job, "en_route")
    add_event(conn, kind="start_route", job_id=job_id, crew_id=crew["crewId"])
    return {"job": job_detail(conn, job_id)}


@app.post("/api/jobs/{job_id}/check-in")
def check_in(job_id: int, body: CheckInIn, crew: Crew, conn: Db) -> dict[str, Any]:
    job = _job_or_404(conn, job_id)
    if job["status"] == "complete":
        raise HTTPException(status_code=409, detail="Job is already complete.")
    if body.lat is None and not body.reason.strip():
        raise HTTPException(
            status_code=400,
            detail="Share GPS or give a reason for checking in without it.",
        )
    ts = now_iso()
    conn.execute(
        """
        UPDATE jobs
        SET check_in_at = ?, check_in_lat = ?, check_in_lng = ?, check_in_accuracy = ?, updated_at = ?
        WHERE id = ?
        """,
        (ts, body.lat, body.lng, body.accuracy, ts, job_id),
    )
    if job["status"] in {"scheduled", "en_route"}:
        _set_status(conn, {**job, "status": job["status"]}, "on_site")
    add_event(
        conn,
        kind="check_in",
        job_id=job_id,
        crew_id=crew["crewId"],
        payload=body.model_dump(),
    )
    return {"job": job_detail(conn, job_id)}


@app.post("/api/jobs/{job_id}/assets")
def add_asset(job_id: int, body: AssetIn, crew: Crew, conn: Db) -> dict[str, Any]:
    job = _job_or_404(conn, job_id)
    if job["status"] == "complete":
        raise HTTPException(status_code=409, detail="Job is already complete.")
    if job["status"] not in {"on_site"}:
        raise HTTPException(status_code=409, detail="Check in on site before logging assets.")
    if not body.serialNumber.strip() and not body.assetTag.strip():
        raise HTTPException(status_code=400, detail="Serial number or asset tag is required.")
    conn.execute(
        """
        INSERT INTO assets (
          job_id, category, serial_number, asset_tag, manufacturer, model, condition,
          data_bearing, destruction_method, notes, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            job_id,
            body.category.strip().lower(),
            body.serialNumber.strip(),
            body.assetTag.strip(),
            body.manufacturer.strip(),
            body.model.strip(),
            body.condition.strip().lower() or "used",
            1 if body.dataBearing else 0,
            body.destructionMethod.strip().lower() or "recycle",
            body.notes.strip(),
            now_iso(),
        ),
    )
    add_event(
        conn,
        kind="asset_add",
        job_id=job_id,
        crew_id=crew["crewId"],
        payload={"serial": body.serialNumber, "tag": body.assetTag, "category": body.category},
    )
    return {"job": job_detail(conn, job_id)}


@app.delete("/api/jobs/{job_id}/assets/{asset_id}")
def delete_asset(job_id: int, asset_id: int, crew: Crew, conn: Db) -> dict[str, Any]:
    job = _job_or_404(conn, job_id)
    if job["status"] == "complete":
        raise HTTPException(status_code=409, detail="Job is already complete.")
    cur = conn.execute(
        "DELETE FROM assets WHERE id = ? AND job_id = ?", (asset_id, job_id)
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Asset not found.")
    add_event(conn, kind="asset_delete", job_id=job_id, crew_id=crew["crewId"], payload={"assetId": asset_id})
    return {"job": job_detail(conn, job_id)}


@app.post("/api/jobs/{job_id}/seals")
def add_seal(job_id: int, body: SealIn, crew: Crew, conn: Db) -> dict[str, Any]:
    job = _job_or_404(conn, job_id)
    if job["status"] == "complete":
        raise HTTPException(status_code=409, detail="Job is already complete.")
    if job["status"] != "on_site":
        raise HTTPException(status_code=409, detail="Check in on site before adding seals.")
    conn.execute(
        "INSERT INTO seals (job_id, code, location, created_at) VALUES (?,?,?,?)",
        (job_id, body.code.strip().upper(), body.location.strip(), now_iso()),
    )
    add_event(
        conn,
        kind="seal_add",
        job_id=job_id,
        crew_id=crew["crewId"],
        payload={"code": body.code},
    )
    return {"job": job_detail(conn, job_id)}


@app.post("/api/jobs/{job_id}/photos")
async def add_photo(
    job_id: int,
    crew: Crew,
    conn: Db,
    file: UploadFile = File(...),
    caption: str = Form(""),
) -> dict[str, Any]:
    job = _job_or_404(conn, job_id)
    if job["status"] == "complete":
        raise HTTPException(status_code=409, detail="Job is already complete.")
    if job["status"] != "on_site":
        raise HTTPException(status_code=409, detail="Check in on site before adding photos.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Photo is empty.")
    if len(content) > 4_000_000:
        raise HTTPException(status_code=400, detail="Photo must be under 4 MB.")
    ext = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"
    name = f"photo-{uuid.uuid4().hex}{ext}"
    (MEDIA_DIR / name).write_bytes(content)
    conn.execute(
        "INSERT INTO photos (job_id, caption, path, created_at) VALUES (?,?,?,?)",
        (job_id, caption.strip(), name, now_iso()),
    )
    add_event(conn, kind="photo_add", job_id=job_id, crew_id=crew["crewId"], payload={"path": name})
    return {"job": job_detail(conn, job_id)}


@app.get("/api/media/{name}")
def get_media(name: str) -> FileResponse:
    if "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid media name.")
    path = MEDIA_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found.")
    return FileResponse(path)


@app.post("/api/jobs/{job_id}/acknowledge")
def acknowledge(job_id: int, body: AcknowledgeIn, crew: Crew, conn: Db) -> dict[str, Any]:
    job = _job_or_404(conn, job_id)
    if job["status"] != "on_site":
        raise HTTPException(status_code=409, detail="Check in on site before sign-off.")
    filename = _save_data_url(body.signatureDataUrl, f"sig-{job_id}")
    conn.execute(
        """
        UPDATE jobs
        SET ack_signer_name = ?, ack_signer_role = ?, ack_signature_path = ?, updated_at = ?
        WHERE id = ?
        """,
        (body.signerName.strip(), body.signerRole.strip(), filename, now_iso(), job_id),
    )
    add_event(
        conn,
        kind="acknowledge",
        job_id=job_id,
        crew_id=crew["crewId"],
        payload={"signer": body.signerName, "role": body.signerRole},
    )
    return {"job": job_detail(conn, job_id)}


@app.post("/api/jobs/{job_id}/complete")
def complete(job_id: int, body: CompleteIn, crew: Crew, conn: Db) -> dict[str, Any]:
    job = _job_or_404(conn, job_id)
    if not job.get("check_in_at"):
        raise HTTPException(status_code=409, detail="Check in on site before completing.")
    if not job.get("ack_signer_name"):
        raise HTTPException(status_code=409, detail="Client sign-off is required.")
    if job["collected_units"] < job["expected_units"] and not body.overrideNote.strip():
        raise HTTPException(
            status_code=409,
            detail="Collected count is under expected. Add an override note to close anyway.",
        )
    _set_status(conn, job, "complete")
    conn.execute(
        "UPDATE jobs SET completed_at = ?, updated_at = ? WHERE id = ?",
        (now_iso(), now_iso(), job_id),
    )
    add_event(
        conn,
        kind="complete",
        job_id=job_id,
        crew_id=crew["crewId"],
        payload={"overrideNote": body.overrideNote, "collected": job["collected_units"]},
    )
    return {"job": job_detail(conn, job_id)}


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse({"error": detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = first.get("loc", ["body"])[-1]
    return JSONResponse(
        {"error": f"Check the {loc} field and try again."},
        status_code=422,
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")

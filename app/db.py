from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from app.config import CREW_PIN, DATABASE_PATH, SESSION_SECRET, ensure_dirs

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS crews (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  pin_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'technician'
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  client_name TEXT NOT NULL,
  site_name TEXT NOT NULL,
  address TEXT NOT NULL,
  city TEXT NOT NULL,
  contact_name TEXT NOT NULL,
  contact_phone TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  expected_units INTEGER NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  assigned_crew_id INTEGER REFERENCES crews(id),
  check_in_at TEXT,
  check_in_lat REAL,
  check_in_lng REAL,
  check_in_accuracy REAL,
  completed_at TEXT,
  ack_signer_name TEXT,
  ack_signer_role TEXT,
  ack_signature_path TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  category TEXT NOT NULL,
  serial_number TEXT NOT NULL DEFAULT '',
  asset_tag TEXT NOT NULL DEFAULT '',
  manufacturer TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  condition TEXT NOT NULL DEFAULT 'used',
  data_bearing INTEGER NOT NULL DEFAULT 0,
  destruction_method TEXT NOT NULL DEFAULT 'recycle',
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seals (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  location TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  caption TEXT NOT NULL DEFAULT '',
  path TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
  crew_id INTEGER REFERENCES crews(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_local_window() -> tuple[str, str]:
    start = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    end = start.replace(hour=12, minute=0)
    return start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")


def pin_hash(pin: str) -> str:
    return hashlib.sha256(f"{SESSION_SECRET}:{pin}".encode()).hexdigest()


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DATABASE_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def job_summary(conn: sqlite3.Connection, job: sqlite3.Row) -> dict[str, Any]:
    data = row_to_dict(job) or {}
    job_id = data["id"]
    collected = conn.execute(
        "SELECT COUNT(*) AS n FROM assets WHERE job_id = ?", (job_id,)
    ).fetchone()["n"]
    seals = conn.execute(
        "SELECT COUNT(*) AS n FROM seals WHERE job_id = ?", (job_id,)
    ).fetchone()["n"]
    photos = conn.execute(
        "SELECT COUNT(*) AS n FROM photos WHERE job_id = ?", (job_id,)
    ).fetchone()["n"]
    crew = None
    if data.get("assigned_crew_id"):
        crew_row = conn.execute(
            "SELECT id, name, role FROM crews WHERE id = ?",
            (data["assigned_crew_id"],),
        ).fetchone()
        crew = row_to_dict(crew_row)
    data["collected_units"] = collected
    data["seal_count"] = seals
    data["photo_count"] = photos
    data["assigned_crew"] = crew
    data["acknowledged"] = bool(data.get("ack_signer_name"))
    return data


def job_detail(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        return None
    data = job_summary(conn, job)
    data["assets"] = [
        row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM assets WHERE job_id = ? ORDER BY id DESC", (job_id,)
        )
    ]
    data["seals"] = [
        row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM seals WHERE job_id = ? ORDER BY id DESC", (job_id,)
        )
    ]
    data["photos"] = [
        row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM photos WHERE job_id = ? ORDER BY id DESC", (job_id,)
        )
    ]
    data["events"] = [
        {
            **(row_to_dict(r) or {}),
            "payload": json.loads(r["payload_json"] or "{}"),
        }
        for r in conn.execute(
            "SELECT * FROM events WHERE job_id = ? ORDER BY id DESC LIMIT 40",
            (job_id,),
        )
    ]
    return data


def add_event(
    conn: sqlite3.Connection,
    *,
    kind: str,
    job_id: int | None,
    crew_id: int | None,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO events (job_id, crew_id, kind, payload_json, created_at) VALUES (?,?,?,?,?)",
        (job_id, crew_id, kind, json.dumps(payload or {}), now_iso()),
    )


def _seed(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
    if existing:
        # Keep PIN in sync with env so Railway rotation works on reboot.
        hashed = pin_hash(CREW_PIN)
        conn.execute("UPDATE crews SET pin_hash = ?", (hashed,))
        return

    hashed = pin_hash(CREW_PIN)
    crews = [
        ("Priya Nair", hashed, "technician"),
        ("Arjun Mehta", hashed, "driver"),
        ("Sana Rahman", hashed, "technician"),
    ]
    for name, pin, role in crews:
        conn.execute(
            "INSERT INTO crews (name, pin_hash, role) VALUES (?,?,?)",
            (name, pin, role),
        )

    priya = conn.execute("SELECT id FROM crews WHERE name = 'Priya Nair'").fetchone()["id"]
    arjun = conn.execute("SELECT id FROM crews WHERE name = 'Arjun Mehta'").fetchone()["id"]
    sana = conn.execute("SELECT id FROM crews WHERE name = 'Sana Rahman'").fetchone()["id"]

    morning_start, morning_end = today_local_window()
    midday = datetime.now().replace(hour=13, minute=0, second=0, microsecond=0)
    midday_end = midday.replace(hour=16, minute=30)
    late = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
    late_end = late.replace(hour=18, minute=0)
    yesterday = datetime.now() - timedelta(days=1)
    y_start = yesterday.replace(hour=10, minute=0, second=0, microsecond=0)
    y_end = y_start.replace(hour=13, minute=0)

    ts = now_iso()
    jobs = [
        (
            "CL-2847",
            "Laptop batch retirement",
            "Infosys",
            "Electronic City campus",
            "Plot 44, Hosur Road, Electronic City Phase 1",
            "Bengaluru",
            "Kavya Iyer",
            "+91 80 4100 2200",
            morning_start,
            morning_end,
            "itad_pickup",
            "scheduled",
            124,
            "Tamper-evident crates already staged at loading bay B. Serial list on contact's desk.",
            priya,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            ts,
            ts,
        ),
        (
            "CL-2848",
            "On-site HDD degauss",
            "HDFC Bank",
            "Koramangala branch",
            "80 Feet Road, Koramangala 4th Block",
            "Bengaluru",
            "Rahul Deshpande",
            "+91 22 6160 6160",
            midday.isoformat(timespec="minutes"),
            midday_end.isoformat(timespec="minutes"),
            "onsite_degauss",
            "en_route",
            38,
            "NSA-evaluated degausser in van. Branch manager must witness destruction.",
            arjun,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            ts,
            ts,
        ),
        (
            "CL-2849",
            "Office decommission",
            "WeWork",
            "Embassy Golf Links",
            "Intermediate Ring Road, Domlur",
            "Bengaluru",
            "Meera Joseph",
            "+91 80 4718 0000",
            late.isoformat(timespec="minutes"),
            late_end.isoformat(timespec="minutes"),
            "office_decommission",
            "on_site",
            67,
            "Mixed PoS, monitors, and docking stations. Loading dock closes 18:30.",
            sana,
            ts,
            12.9592,
            77.6408,
            12.0,
            None,
            None,
            None,
            None,
            ts,
            ts,
        ),
        (
            "CL-2831",
            "Network gear recycle",
            "Freshworks",
            "Prestige Tech Park",
            "Sarjapur-Marathahalli Road, Kadubeesanahalli",
            "Bengaluru",
            "Ankit Rao",
            "+91 44 7153 2000",
            y_start.isoformat(timespec="minutes"),
            y_end.isoformat(timespec="minutes"),
            "itad_pickup",
            "complete",
            42,
            "Sealed and handed to Bengaluru facility inbound.",
            priya,
            (yesterday.replace(hour=10, minute=18)).isoformat(timespec="seconds"),
            12.9355,
            77.6947,
            8.0,
            (yesterday.replace(hour=12, minute=40)).isoformat(timespec="seconds"),
            "Ankit Rao",
            "Facilities lead",
            None,
            ts,
            ts,
        ),
    ]

    conn.executemany(
        """
        INSERT INTO jobs (
          code, title, client_name, site_name, address, city, contact_name, contact_phone,
          window_start, window_end, job_type, status, expected_units, notes, assigned_crew_id,
          check_in_at, check_in_lat, check_in_lng, check_in_accuracy, completed_at,
          ack_signer_name, ack_signer_role, ack_signature_path, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        jobs,
    )

    wework = conn.execute("SELECT id FROM jobs WHERE code = 'CL-2849'").fetchone()["id"]
    done = conn.execute("SELECT id FROM jobs WHERE code = 'CL-2831'").fetchone()["id"]

    conn.execute(
        """
        INSERT INTO assets (job_id, category, serial_number, asset_tag, manufacturer, model, condition, data_bearing, destruction_method, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            wework,
            "monitor",
            "DEL-U2720-4412",
            "WW-IT-8891",
            "Dell",
            "U2720Q",
            "used",
            0,
            "recycle",
            "Stand intact",
            ts,
        ),
    )
    conn.execute(
        """
        INSERT INTO assets (job_id, category, serial_number, asset_tag, manufacturer, model, condition, data_bearing, destruction_method, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            wework,
            "laptop",
            "MBP-C02XK1QJ",
            "WW-IT-2204",
            "Apple",
            "MacBook Pro 14",
            "fair",
            1,
            "wipe",
            "FileVault on — still needs NIST wipe",
            ts,
        ),
    )
    conn.execute(
        "INSERT INTO seals (job_id, code, location, created_at) VALUES (?,?,?,?)",
        (wework, "URN-SEAL-11029", "crate A", ts),
    )
    conn.execute(
        """
        INSERT INTO assets (job_id, category, serial_number, asset_tag, manufacturer, model, condition, data_bearing, destruction_method, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            done,
            "network",
            "CS-3850-991",
            "FW-NET-12",
            "Cisco",
            "Catalyst 3850",
            "used",
            0,
            "recycle",
            "",
            ts,
        ),
    )
    conn.execute(
        "INSERT INTO seals (job_id, code, location, created_at) VALUES (?,?,?,?)",
        (done, "URN-SEAL-10901", "pallet 1", ts),
    )
    add_event(
        conn,
        kind="check_in",
        job_id=wework,
        crew_id=sana,
        payload={"lat": 12.9592, "lng": 77.6408},
    )
    add_event(
        conn,
        kind="complete",
        job_id=done,
        crew_id=priya,
        payload={"collected": 1},
    )

"""Daily production backup on the same DATA_DIR volume.

Keeps 30 daily snapshots and 12 monthly copies. Never deletes the live register.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import (
    BACKUP_DIR,
    BACKUP_HOUR_UTC,
    BACKUP_KEEP_DAILY,
    BACKUP_KEEP_MONTHLY,
    BACKUP_MINUTE_UTC,
    BACKUP_STALE_HOURS,
    BACKUP_STARTUP_DELAY_SEC,
    DATA_DIR,
    STATE_PATH,
    backup_enabled,
    ensure_dirs,
)
from app.store import replace_state_bytes, snapshot_state_bytes

log = logging.getLogger("circuitloop.backup")

BACKUP_STATE_NAME = "circuitloop-state.json"
MANIFEST_NAME = "manifest.json"
SKIP_NAMES = {BACKUP_DIR.name}
SKIP_SUFFIXES = {".tmp"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(now: datetime | None = None) -> str:
    current = now or _utc_now()
    return current.strftime("%Y%m%dT%H%M%S") + f"{current.microsecond:06d}Z"


def schedule_label() -> str:
    return (
        f"daily at {BACKUP_HOUR_UTC:02d}:{BACKUP_MINUTE_UTC:02d} UTC "
        f"(plus catch-up after start if the last backup is older than "
        f"{int(BACKUP_STALE_HOURS)}h)"
    )


def _is_daily_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and path.name.startswith("circuitloop-")
        and not path.name.startswith("circuitloop-monthly-")
        and not path.name.startswith(".")
    )


def _is_monthly_dir(path: Path) -> bool:
    return path.is_dir() and path.name.startswith("circuitloop-monthly-")


def _is_backup_dir(path: Path) -> bool:
    return _is_daily_dir(path)


def list_backup_dirs() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(
        (p for p in BACKUP_DIR.iterdir() if _is_daily_dir(p)),
        key=lambda p: p.name,
    )


def list_monthly_dirs() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(
        (p for p in BACKUP_DIR.iterdir() if _is_monthly_dir(p)),
        key=lambda p: p.name,
    )


def latest_backup_dir() -> Path | None:
    dirs = list_backup_dirs()
    return dirs[-1] if dirs else None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_manifest(path: Path) -> dict[str, Any] | None:
    manifest_path = path / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def public_backup_status() -> dict[str, Any]:
    """Health payload: no filesystem paths."""
    full = backup_status()
    latest = full.get("latest") or None
    pub_latest = None
    if latest:
        pub_latest = {
            "id": latest.get("id"),
            "createdAt": latest.get("createdAt"),
            "bytes": latest.get("bytes"),
            "rev": latest.get("rev"),
        }
    return {
        "enabled": full.get("enabled"),
        "schedule": full.get("schedule"),
        "keepDaily": full.get("keepDaily"),
        "keepMonthly": full.get("keepMonthly"),
        "latest": pub_latest,
    }


def backup_status() -> dict[str, Any]:
    latest = latest_backup_dir()
    payload: dict[str, Any] = {
        "enabled": backup_enabled(),
        "dir": str(BACKUP_DIR),
        "schedule": schedule_label(),
        "keepDaily": BACKUP_KEEP_DAILY,
        "keepMonthly": BACKUP_KEEP_MONTHLY,
        "keep": BACKUP_KEEP_DAILY,
        "rotation": (
            f"keep {BACKUP_KEEP_DAILY} daily snapshots and {BACKUP_KEEP_MONTHLY} "
            "monthly copies on this volume"
        ),
        "latest": None,
    }
    if latest is None:
        return payload
    manifest = _read_manifest(latest) or {}
    state_file = latest / BACKUP_STATE_NAME
    payload["latest"] = {
        "id": latest.name,
        "path": str(latest),
        "createdAt": manifest.get("createdAt"),
        "bytes": manifest.get("bytes") or (state_file.stat().st_size if state_file.exists() else 0),
        "sha256": manifest.get("sha256"),
        "rev": manifest.get("rev"),
        "files": manifest.get("files") or [p.name for p in latest.iterdir() if p.is_file()],
    }
    return payload


def _extra_live_files() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    extras: list[Path] = []
    for path in DATA_DIR.iterdir():
        if path.name in SKIP_NAMES:
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        if path.resolve() == BACKUP_DIR.resolve():
            continue
        if path.resolve() == STATE_PATH.resolve():
            continue
        if path.is_file() and not path.name.startswith("."):
            extras.append(path)
    return extras


def _write_staging(staging: Path, raw: bytes, parsed: dict[str, Any], now: datetime) -> dict[str, Any]:
    staging.mkdir(parents=True, exist_ok=False)
    state_path = staging / BACKUP_STATE_NAME
    state_path.write_bytes(raw)
    files = [BACKUP_STATE_NAME]
    for extra in _extra_live_files():
        shutil.copy2(extra, staging / extra.name)
        files.append(extra.name)
    roundtrip = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(roundtrip, dict) or "assets" not in roundtrip or "projects" not in roundtrip:
        raise ValueError("Backup copy did not verify as a CircuitLoop register.")
    manifest = {
        "createdAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sourceStatePath": str(STATE_PATH),
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "rev": parsed.get("_rev"),
        "savedAt": parsed.get("_savedAt"),
        "files": files,
        "keepDaily": BACKUP_KEEP_DAILY,
        "keepMonthly": BACKUP_KEEP_MONTHLY,
    }
    (staging / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _cleanup_incoming() -> None:
    if not BACKUP_DIR.exists():
        return
    for path in BACKUP_DIR.iterdir():
        if path.name.startswith(".incoming-"):
            shutil.rmtree(path, ignore_errors=True)


def _rotate_dailies() -> list[str]:
    removed: list[str] = []
    dailies = list_backup_dirs()
    extra = dailies[: max(0, len(dailies) - BACKUP_KEEP_DAILY)]
    for path in extra:
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def _rotate_monthlies() -> list[str]:
    removed: list[str] = []
    monthlies = list_monthly_dirs()
    extra = monthlies[: max(0, len(monthlies) - BACKUP_KEEP_MONTHLY)]
    for path in extra:
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def _ensure_monthly(final: Path, now: datetime) -> str | None:
    stamp = now.strftime("%Y-%m")
    dest = BACKUP_DIR / f"circuitloop-monthly-{stamp}"
    if dest.exists():
        return None
    shutil.copytree(final, dest)
    return dest.name


def run_backup() -> dict[str, Any]:
    """Copy live production state into BACKUP_DIR, then delete previous backups.

    If anything fails before the new backup is verified, the previous backup is kept
    and the live register is not touched.
    """
    ensure_dirs()
    now = _utc_now()
    raw = snapshot_state_bytes()
    if raw is None:
        log.warning("daily backup skipped: no live register at %s", STATE_PATH)
        return {
            "ok": False,
            "reason": "no live register to copy",
            "livePath": str(STATE_PATH),
            "previousKept": True,
        }
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Live register is not a JSON object; backup aborted.")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_incoming()
    stamp = _stamp(now)
    staging = BACKUP_DIR / f".incoming-{stamp}"
    final = BACKUP_DIR / f"circuitloop-{stamp}"
    suffix = 1
    while final.exists():
        suffix += 1
        final = BACKUP_DIR / f"circuitloop-{stamp}-{suffix}"
    try:
        manifest = _write_staging(staging, raw, parsed, now)
        staging.rename(final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        log.exception("daily backup failed before rotate; previous backup kept")
        raise

    monthly = _ensure_monthly(final, now)
    removed = _rotate_dailies() + _rotate_monthlies()
    result = {
        "ok": True,
        "id": final.name,
        "path": str(final),
        "livePath": str(STATE_PATH),
        "monthly": monthly,
        "removed": removed,
        **manifest,
    }
    log.info(
        "daily backup %s (%s bytes, rev %s); removed %s",
        final.name,
        manifest["bytes"],
        manifest.get("rev"),
        removed or "none",
    )
    print(
        f"circuitloop backup {final.name} bytes={manifest['bytes']} "
        f"rev={manifest.get('rev')} removed={removed or 'none'}",
        flush=True,
    )
    return result


def restore_latest() -> dict[str, Any]:
    """Replace the live register with the latest backup. Manual / CLI only."""
    latest = latest_backup_dir()
    if latest is None:
        raise FileNotFoundError(f"No backup found in {BACKUP_DIR}")
    state_file = latest / BACKUP_STATE_NAME
    if not state_file.exists():
        raise FileNotFoundError(f"Backup {latest} has no {BACKUP_STATE_NAME}")
    raw = state_file.read_bytes()
    replace_state_bytes(raw)
    parsed = json.loads(raw.decode("utf-8"))
    log.info("restored live register from %s (rev %s)", latest.name, parsed.get("_rev"))
    return {
        "ok": True,
        "restoredFrom": str(latest),
        "livePath": str(STATE_PATH),
        "rev": parsed.get("_rev"),
        "bytes": len(raw),
        "sha256": _sha256(raw),
    }


def needs_catchup(now: datetime | None = None) -> bool:
    latest = latest_backup_dir()
    if latest is None:
        return True
    manifest = _read_manifest(latest) or {}
    created = manifest.get("createdAt")
    if not created:
        return True
    try:
        stamped = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    age = (now or _utc_now()) - stamped
    return age >= timedelta(hours=BACKUP_STALE_HOURS)


def seconds_until_next_run(now: datetime | None = None) -> float:
    current = now or _utc_now()
    target = current.replace(
        hour=BACKUP_HOUR_UTC,
        minute=BACKUP_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    if target <= current:
        target += timedelta(days=1)
    return max(1.0, (target - current).total_seconds())


async def backup_loop() -> None:
    await asyncio.sleep(max(0.0, BACKUP_STARTUP_DELAY_SEC))
    if backup_enabled() and needs_catchup():
        try:
            run_backup()
        except Exception:
            log.exception("startup catch-up backup failed; previous backup kept")
    while True:
        await asyncio.sleep(seconds_until_next_run())
        if not backup_enabled():
            continue
        try:
            run_backup()
        except Exception:
            log.exception("scheduled daily backup failed; previous backup kept")


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "status"
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if cmd == "run":
        print(json.dumps(run_backup(), indent=2))
        return 0
    if cmd == "restore":
        print(json.dumps(restore_latest(), indent=2))
        return 0
    if cmd == "status":
        print(json.dumps(backup_status(), indent=2))
        return 0
    print("Usage: python -m app.backup [status|run|restore]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

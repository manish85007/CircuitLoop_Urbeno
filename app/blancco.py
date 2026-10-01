"""Blancco lookup. Production stores only live API reports — never simulated ones."""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from app.config import BLANCCO_API_KEY, BLANCCO_ENDPOINT


async def lookup(serial: str, category: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or {}
    if category != "Laptop":
        return {
            "ok": False,
            "error": f"Blancco integration is restricted to Laptops. {category} uses the manual sanitization test parameter.",
        }
    serial = str(serial or "").strip()
    if not serial or serial.lower().startswith("noserial"):
        return {"ok": False, "error": "Blancco lookup needs a factory serial (NoSerial devices are skipped)."}
    endpoint = (cfg.get("endpoint") or BLANCCO_ENDPOINT or "").strip()
    key = BLANCCO_API_KEY
    if not key:
        return {
            "ok": False,
            "error": "Blancco API key is not configured on the server (set BLANCCO_API_KEY). Simulated reports are disabled.",
        }
    if not endpoint:
        return {"ok": False, "error": "Blancco API endpoint is not configured."}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.get(
                endpoint,
                params={"serial": serial},
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            res.raise_for_status()
            payload = res.json()
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": f"Blancco API returned HTTP {exc.response.status_code}."}
    except Exception:
        return {"ok": False, "error": "Blancco API lookup failed. No report stored."}

    report = None
    if isinstance(payload, dict) and payload.get("report"):
        report = payload["report"]
    elif isinstance(payload, dict) and payload.get("reportId"):
        report = payload
    if not isinstance(report, dict) or not report.get("reportId"):
        return {"ok": False, "error": "Blancco API did not return a report for that serial."}
    report = dict(report)
    report["serial"] = report.get("serial") or serial
    report["source"] = "Blancco API"
    return {"ok": True, "report": report}


def require_live_report(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Blancco lookup failed.")
    return result["report"]

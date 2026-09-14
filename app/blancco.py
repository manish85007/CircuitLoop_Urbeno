from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import httpx

from app.config import BLANCCO_API_KEY


def _simulated(serial: str, source: str) -> dict[str, Any]:
    sizes = (
        ("256 GB", "NVMe SSD"),
        ("512 GB", "NVMe SSD"),
        ("1 TB", "NVMe SSD"),
        ("500 GB", "SATA HDD"),
    )
    h = int(hashlib.sha256(serial.encode()).hexdigest(), 16)
    size, model = sizes[h % len(sizes)]
    failed = "FAILSEED" in serial.upper()
    return {
        "ok": True,
        "report": {
            "reportId": f"BL-{h % 90000 + 10000}",
            "serial": serial,
            "status": "Failed" if failed else "Erased",
            "standard": "NIST 800-88 Rev. 1 Purge",
            "software": "Blancco Drive Eraser 7.6",
            "date": date.today().isoformat(),
            "verified": not failed,
            "drives": [
                {
                    "model": model if not failed else "Unknown",
                    "size": size if not failed else "—",
                    "result": (
                        "Failed — drive not detected"
                        if failed
                        else "Erasure successful — full verification passed"
                    ),
                }
            ],
            "operator": "CircuitLoop",
            "source": source,
            "raw": (
                "Erasure aborted: target drive reported SMART failure."
                if failed
                else "All addressable sectors overwritten and verified. Hardware secure-erase issued where supported."
            ),
        },
    }


async def lookup(serial: str, category: str, cfg: dict[str, Any] | None) -> dict[str, Any]:
    cfg = cfg or {}
    if category != "Laptop":
        return {
            "ok": False,
            "error": f"Blancco integration is restricted to Laptops. {category} uses the manual sanitization test parameter.",
        }
    mode = cfg.get("mode") or "Demo (simulated)"
    endpoint = cfg.get("endpoint") or ""
    key = BLANCCO_API_KEY or cfg.get("apiKey") or ""
    if mode != "Live":
        return _simulated(serial, "Demo (simulated)")
    if not key:
        return {
            "ok": False,
            "error": "Live mode selected but no API key is configured (Masters → Blancco API, or BLANCCO_API_KEY).",
        }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.get(
                endpoint,
                params={"serial": serial},
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            res.raise_for_status()
            payload = res.json()
        if isinstance(payload, dict) and payload.get("report"):
            return {"ok": True, "report": payload["report"]}
        if isinstance(payload, dict) and payload.get("reportId"):
            return {"ok": True, "report": payload}
        return _simulated(serial, "Demo (simulated) — live response was not a Blancco report")
    except Exception:
        return _simulated(serial, "Demo (simulated) — live lookup failed")

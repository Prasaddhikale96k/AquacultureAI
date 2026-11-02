"""DO prediction and kit-reading routes (Track II D1)."""
from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from backend.app.services import do_model, do_service


def _err(status, message, **kw):
    return JSONResponse({"error": message, **kw}, status_code=status)


def _number(raw):
    if isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _iso_utc(raw):
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def do_prediction(_):
    return JSONResponse(do_service.prediction())


async def post_do_reading(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _err(400, "Send a JSON body.")
    if not isinstance(body, dict):
        return _err(400, "Send a JSON object.")
    value = _number(body.get("value_mgl"))
    if value is None or value < 0 or value > 20:
        return _err(422, "Validation failed.", fields={"value_mgl": "Required number from 0 to 20 mg/L."})
    measured = _iso_utc(body.get("measured_at") or datetime.now(timezone.utc).isoformat())
    if measured is None:
        return _err(422, "Validation failed.", fields={"measured_at": "Must be an ISO date-time."})
    method = str(body.get("method") or "test_kit").strip()[:64] or "test_kit"
    pred = do_service.prediction()
    rec = {
        "id": uuid.uuid4().hex,
        "value_mgl": round(value, 2),
        "measured_at": measured.isoformat(),
        "measured_t": measured.timestamp(),
        "method": method,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "do_est": pred.get("do_mgl") if pred.get("status") == "ok" else None,
        "model_version": do_model.MODEL_VERSION,
        "provisional": True,
    }
    do_service.append_reading(rec)
    do_service.maybe_fit()
    return JSONResponse({"reading": rec}, status_code=201)


async def get_do_readings(request: Request):
    try:
        limit = int(request.query_params.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    rows = do_service.recent_readings(limit)
    return JSONResponse({"readings": rows, "count": len(rows),
                         "provisional": True, "model_version": do_model.MODEL_VERSION})


ROUTES = [
    Route("/api/do-prediction", do_prediction),
    Route("/api/water/do-reading", post_do_reading, methods=["POST"]),
    Route("/api/water/do-readings", get_do_readings),
]

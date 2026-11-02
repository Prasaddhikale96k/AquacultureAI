"""Feeding log routes (Track IV F1)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from backend.app.services import feeding_service


def _err(status, message, **kw):
    return JSONResponse({"error": message, **kw}, status_code=status)


def _epoch(raw):
    if raw is None:
        return time.time()
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


async def post_feeding(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _err(400, "Send a JSON body.")
    if not isinstance(body, dict):
        return _err(400, "Send a JSON object.")
    fed_t = _epoch(body.get("fed_at"))
    if fed_t is None:
        return _err(422, "Validation failed.", fields={"fed_at": "Must be an ISO date-time."})
    if fed_t > time.time() + 300:
        return _err(422, "Validation failed.", fields={"fed_at": "Cannot be in the future."})
    try:
        rec = feeding_service.log_feeding(fed_t, body.get("note"))
    except PermissionError as e:
        return _err(403, str(e))
    updated = feeding_service.update_responses()
    row = next((r for r in updated if r.get("id") == rec["id"]), rec)
    return JSONResponse({"feeding": row}, status_code=201)


async def get_feeding(_):
    if not feeding_service.enabled():
        return JSONResponse({"enabled": False, "feedings": [], "count": 0})
    feeding_service.update_responses()
    rows = feeding_service.read_events(30)
    return JSONResponse({
        "enabled": True,
        "feedings": rows[-100:],
        "count": len(rows),
        "today": feeding_service.counts_today(),
        "latest": feeding_service.latest(),
        "dip": feeding_service.feed_effect(),
        "provisional": True,
        "model_version": feeding_service.MODEL_VERSION,
    })


ROUTES = [
    Route("/api/feeding", get_feeding),
    Route("/api/feeding", post_feeding, methods=["POST"]),
]

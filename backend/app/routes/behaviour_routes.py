"""Behaviour window routes (Track III BEH-A/BEH-B)."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from backend.app.services import behaviour_service


async def post_observation(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Send a JSON body."}, status_code=400)
    try:
        rec, summary, sms = behaviour_service.record_observation(payload)
    except ValueError as e:
        return JSONResponse({"error": "Validation failed.", "reason": str(e)}, status_code=422)
    return JSONResponse({"observation": rec, "summary": summary, "alert_sent": bool(sms)}, status_code=201)


async def get_summary(_):
    return JSONResponse(behaviour_service.summary())


ROUTES = [
    Route("/api/behaviour/observations", post_observation, methods=["POST"]),
    Route("/api/behaviour/summary", get_summary),
]

"""Starlette HTTP endpoints for Authentication & User Registration."""
from __future__ import annotations

import json
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from backend.app.auth import otp, store, tokens

SESSION_COOKIE = "aqua_session"
CSRF_COOKIE = "aqua_csrf"


async def auth_register(request: Request) -> Response:
    """POST /api/auth/register {name, phone, tankId, species, system}"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "reason": "Invalid JSON payload"}, status_code=400)

    name = str(body.get("name") or "").strip()
    phone_raw = str(body.get("phone") or "").strip()
    tank_id = str(body.get("tankId") or "").strip()
    species = str(body.get("species") or "").strip() or "Nile Tilapia (GIFT)"
    system = str(body.get("system") or "").strip() or "RAS"

    if not name:
        return JSONResponse({"ok": False, "reason": "Name is required"}, status_code=400)
    if not phone_raw:
        return JSONResponse({"ok": False, "reason": "Phone number is required"}, status_code=400)

    normalized = otp.normalize_phone(phone_raw)
    if not normalized:
        return JSONResponse({"ok": False, "reason": "Valid 10-digit phone number is required (+91)"}, status_code=400)

    # Store unverified user profile
    user_record = {
        "name": name,
        "phone": normalized,
        "tankId": tank_id,
        "species": species,
        "system": system,
        "verified": False,
    }
    store.save_user(user_record)

    # Dispatch OTP via alert provider chain
    ok, msg, meta = otp.generate_and_send_otp(normalized)
    if not ok:
        return JSONResponse({"ok": False, "reason": msg}, status_code=429 if "Too many" in msg or "wait" in msg else 400)

    return JSONResponse({
        "ok": True,
        "message": msg,
        "phone_masked": meta.get("phone_masked") if meta else otp.mask_phone(normalized),
        "cooldown_s": meta.get("cooldown_s", 30) if meta else 30,
        "expires_in_s": meta.get("expires_in_s", 300) if meta else 300,
    })


async def auth_login(request: Request) -> Response:
    """POST /api/auth/login {phone} -> 404-safe OTP dispatch"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "reason": "Invalid JSON payload"}, status_code=400)

    phone_raw = str(body.get("phone") or "").strip()
    normalized = otp.normalize_phone(phone_raw)
    if not normalized:
        return JSONResponse({"ok": False, "reason": "Valid 10-digit phone number is required"}, status_code=400)

    # 404-safe dispatch: we generate OTP for the phone regardless of prior registration
    ok, msg, meta = otp.generate_and_send_otp(normalized)
    if not ok:
        return JSONResponse({"ok": False, "reason": msg}, status_code=429 if "Too many" in msg or "wait" in msg else 400)

    return JSONResponse({
        "ok": True,
        "message": "OTP sent if registered",
        "phone_masked": meta.get("phone_masked") if meta else otp.mask_phone(normalized),
        "cooldown_s": meta.get("cooldown_s", 30) if meta else 30,
        "expires_in_s": meta.get("expires_in_s", 300) if meta else 300,
    })


async def auth_verify(request: Request) -> Response:
    """POST /api/auth/verify {phone, otp} -> validates OTP, issues HttpOnly cookie and CSRF token"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "reason": "Invalid JSON payload"}, status_code=400)

    phone_raw = str(body.get("phone") or "").strip()
    code = str(body.get("otp") or "").strip()

    normalized = otp.normalize_phone(phone_raw)
    if not normalized or not code:
        return JSONResponse({"ok": False, "reason": "Phone and OTP are required"}, status_code=400)

    ok, msg = otp.verify_otp(normalized, code)
    if not ok:
        return JSONResponse({"ok": False, "reason": msg}, status_code=401)

    # Mark user as verified if present, or create minimal record
    user = store.get_user(normalized)
    if user:
        user["verified"] = True
        store.save_user(user)
    else:
        user = store.save_user({
            "name": "Farmer",
            "phone": normalized,
            "tankId": "Tank-01",
            "species": "Nile Tilapia (GIFT)",
            "system": "RAS",
            "verified": True,
        })

    # Subscribe this verified number to SMS alerts
    from backend import auth as alert_auth
    alert_auth.mark_verified(normalized)

    # Create session
    raw_token, csrf_token = tokens.create_session(normalized)

    response = JSONResponse({
        "ok": True,
        "user": {
            "name": user.get("name"),
            "phone": user.get("phone"),
            "tankId": user.get("tankId"),
            "species": user.get("species"),
            "system": user.get("system"),
        },
        "token": raw_token,  # Bearer fallback for pytest/APIs
        "csrf_token": csrf_token,
    })

    # Deliver session as HttpOnly, Lax cookie (protects against XSS)
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=7 * 86400,
        httponly=True,
        samesite="lax",
        secure=False,  # LAN deployment friendly
        path="/",
    )
    # Deliver CSRF double-submit token as accessible cookie
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=7 * 86400,
        httponly=False,
        samesite="lax",
        secure=False,
        path="/",
    )

    return response


async def auth_resend(request: Request) -> Response:
    """POST /api/auth/resend {phone}"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "reason": "Invalid JSON payload"}, status_code=400)

    phone_raw = str(body.get("phone") or "").strip()
    normalized = otp.normalize_phone(phone_raw)
    if not normalized:
        return JSONResponse({"ok": False, "reason": "Phone number is required"}, status_code=400)

    ok, msg, meta = otp.generate_and_send_otp(normalized)
    if not ok:
        return JSONResponse({"ok": False, "reason": msg}, status_code=429 if "wait" in msg or "Too many" in msg else 400)

    return JSONResponse({
        "ok": True,
        "message": "OTP resent successfully",
        "phone_masked": meta.get("phone_masked") if meta else otp.mask_phone(normalized),
        "cooldown_s": meta.get("cooldown_s", 30) if meta else 30,
    })


async def auth_remove_phone(request: Request) -> Response:
    """POST /api/auth/remove-phone {phone} -> removes a verified phone from SMS alert recipients

    Accepts either a full normalized number (e.g. +919876543210) or a masked
    value (e.g. ***123) as returned by the phones_masked list. Masked values are
    matched against verified phones by last-3 digits inside unverify_phone().
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "reason": "Invalid JSON payload"}, status_code=400)
    phone_raw = str(body.get("phone") or "").strip()
    if not phone_raw:
        return JSONResponse({"ok": False, "reason": "Valid phone number is required"}, status_code=400)
    ok = alert_auth.unverify_phone(phone_raw)
    if not ok:
        return JSONResponse({"ok": False, "reason": "Invalid phone number"}, status_code=400)
    return JSONResponse({"ok": True, "phone_masked": alert_auth.mask(phone_raw)})


async def auth_logout(request: Request) -> Response:
    """POST /api/auth/logout"""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        tokens.revoke_session(token)

    response = JSONResponse({"ok": True, "message": "Logged out successfully"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


async def auth_me(request: Request) -> Response:
    """GET /api/auth/me -> Returns current user profile"""
    user_phone = getattr(request.state, "user_phone", None)
    if not user_phone:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
        if token:
            sess = tokens.validate_session(token)
            if sess:
                user_phone = sess.get("phone")

    if not user_phone:
        return JSONResponse({"ok": False, "reason": "Not authenticated"}, status_code=401)

    user = store.get_user(user_phone)
    if not user:
        user = {"phone": user_phone, "name": "Farmer", "verified": True}

    return JSONResponse({
        "ok": True,
        "user": {
            "name": user.get("name"),
            "phone": user.get("phone"),
            "tankId": user.get("tankId"),
            "species": user.get("species"),
            "system": user.get("system"),
        }
    })


ROUTES = [
    Route("/api/auth/register", auth_register, methods=["POST"]),
    Route("/api/auth/login", auth_login, methods=["POST"]),
    Route("/api/auth/verify", auth_verify, methods=["POST"]),
    Route("/api/auth/resend", auth_resend, methods=["POST"]),
    Route("/api/auth/logout", auth_logout, methods=["POST"]),
    Route("/api/auth/remove-phone", auth_remove_phone, methods=["POST"]),
    Route("/api/auth/me", auth_me, methods=["GET"]),
]

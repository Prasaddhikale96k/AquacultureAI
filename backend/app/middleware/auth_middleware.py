"""Starlette authentication and CSRF middleware.

AUTH DESIGN DECISION:
Session token delivered as an HttpOnly, Secure(if TLS)/SameSite=Lax cookie — chosen over a
Bearer-in-localStorage token because farm devices are often shared tablets/browsers on a LAN;
HttpOnly cookies are immune to XSS-based token theft. A CSRF double-submit token
(X-CSRF-Token header mirrored in a non-HttpOnly cookie) is issued at verify-time and required
on all state-changing /api/* calls to mitigate CSRF. Document a Bearer-header fallback path
for the pytest client / non-browser tools (Authorization: Bearer <token> accepted
interchangeably with the cookie).
"""
from __future__ import annotations

import os
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.app.auth import tokens

SESSION_COOKIE = "aqua_session"
CSRF_HEADER = "x-csrf-token"

# Paths that do not require authentication
PUBLIC_PREFIXES = (
    "/health",
    "/api/diagnostics",
    "/api/auth/",
    "/favicon.ico",
    "/static/",
    "/assets/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Preflight CORS requests pass through
        if request.method == "OPTIONS":
            return await call_next(request)

        mode = os.environ.get("AQUA_AUTH_MODE", "full").lower()
        if mode == "open":
            # Instant rollback switch: open mode allows unauthenticated access
            return await call_next(request)

        path = request.url.path

        # Static assets and non-api paths pass through
        if not path.startswith("/api/"):
            return await call_next(request)

        # Allow-list for public auth endpoints and health check
        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix) or path == prefix.rstrip("/"):
                return await call_next(request)

        # Extract session token: cookie first, then Bearer fallback
        token = request.cookies.get(SESSION_COOKIE)
        used_bearer = False
        if not token:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
                used_bearer = True

        if not token:
            return JSONResponse(
                {"ok": False, "reason": "Authentication required. Please login."},
                status_code=401,
            )

        # In-memory session validation (zero disk read per request per A4)
        sess = tokens.validate_session(token)
        if not sess:
            return JSONResponse(
                {"ok": False, "reason": "Session expired or invalid. Please login."},
                status_code=401,
            )

        # CSRF check on mutating requests when cookie authentication is used
        if not used_bearer and request.method in ("POST", "PUT", "DELETE", "PATCH"):
            csrf_header = request.headers.get(CSRF_HEADER)
            expected_csrf = sess.get("csrf_token")
            if not csrf_header or csrf_header != expected_csrf:
                return JSONResponse(
                    {"ok": False, "reason": "CSRF token missing or invalid"},
                    status_code=403,
                )

        request.state.user_phone = sess.get("phone")
        return await call_next(request)

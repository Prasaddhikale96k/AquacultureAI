"""OTP generation, hashing, rate limiting, and delivery via SMSGate/TextBee chain.

AUTH DESIGN DECISION:
Session token delivered as an HttpOnly, Secure(if TLS)/SameSite=Lax cookie — chosen over
a Bearer-in-localStorage token because farm devices are often shared tablets/browsers on a LAN;
HttpOnly cookies are immune to XSS-based token theft. A CSRF double-submit token
(X-CSRF-Token header mirrored in a non-HttpOnly cookie) is issued at verify-time and required
on all state-changing /api/* calls to mitigate CSRF. An Authorization: Bearer <token> fallback
path is supported for pytest / non-browser API clients.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from typing import Dict, List, Optional, Tuple

from backend import alerts

_lock = threading.RLock()
_otps: Dict[str, dict] = {}       # phone -> {hash, salt, exp, attempts, created_at}
_req_history: Dict[str, List[float]] = {}  # phone -> list of timestamps

OTP_EXPIRY_SECONDS = 300       # 5 minutes
RESEND_COOLDOWN_SECONDS = 30   # 30s cooldown
MAX_VERIFY_ATTEMPTS = 3        # Lockout after 3 wrong tries
MAX_OTP_PER_HOUR = 5           # Rate limit: 5 OTPs per hour per phone


def normalize_phone(raw: str) -> Optional[str]:
    """Normalize phone to international E.164-style (+91XXXXXXXXXX)."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        digits = "91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    if 10 <= len(digits) <= 15:
        return "+" + digits
    return None


def mask_phone(phone: str) -> str:
    """Mask phone number for privacy display (e.g. +91 9•••••123)."""
    ph = normalize_phone(phone) or phone or ""
    if ph.startswith("+91") and len(ph) == 13:
        # Format: +91 9•••••123
        return f"+91 {ph[3]}•••••{ph[-3:]}"
    if len(ph) >= 4:
        return ph[:3] + "••••" + ph[-3:]
    return ph


def _hash_otp(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def generate_and_send_otp(phone: str, now: Optional[float] = None) -> Tuple[bool, str, Optional[dict]]:
    """Generate 6-digit OTP, enforce rate limits & cooldowns, and dispatch via alert provider chain."""
    now = time.time() if now is None else float(now)
    ph = normalize_phone(phone)
    if not ph:
        return False, "Invalid phone number (+91 required)", None

    with _lock:
        # Rate limit check (5 OTP per hour)
        history = [t for t in _req_history.get(ph, []) if now - t < 3600]
        if len(history) >= MAX_OTP_PER_HOUR:
            return False, "Too many OTP requests. Maximum 5 per hour. Please try later.", None

        # Resend cooldown check (30s)
        current = _otps.get(ph)
        if current and (now - current.get("created_at", 0)) < RESEND_COOLDOWN_SECONDS:
            remaining = int(RESEND_COOLDOWN_SECONDS - (now - current.get("created_at", 0)))
            return False, f"Please wait {remaining}s before requesting a new OTP.", None

        # Generate 6-digit code
        code = f"{secrets.randbelow(900000) + 100000:06d}"
        salt = secrets.token_hex(16)
        hashed = _hash_otp(code, salt)

        _otps[ph] = {
            "hash": hashed,
            "salt": salt,
            "exp": now + OTP_EXPIRY_SECONDS,
            "attempts": 0,
            "created_at": now,
        }
        _req_history[ph] = history + [now]

    # English OTP SMS template (<= 160 chars)
    msg = f"AquaAI OTP: {code}. Verify within 5 min. Do not share it. -AquaAI"
    # Send through existing alert provider chain (smsgate -> textbee -> log)
    delivery = alerts.send_alert(
        "OTP",
        msg,
        "INFO",
        now=now,
        force=True,
        phones=[ph],
        log_message="OTP sent (code redacted)",
    )

    meta = {
        "phone_masked": mask_phone(ph),
        "cooldown_s": RESEND_COOLDOWN_SECONDS,
        "expires_in_s": OTP_EXPIRY_SECONDS,
        "delivered": delivery.get("delivered", False),
        "providers": delivery.get("providers", []),
        "statuses": delivery.get("statuses", {}),
    }

    return True, "OTP sent successfully", meta


def verify_otp(phone: str, code: str, now: Optional[float] = None) -> Tuple[bool, str]:
    """Verify submitted 6-digit OTP code against salt/hash with 3-attempt lockout and 5-min expiry."""
    now = time.time() if now is None else float(now)
    ph = normalize_phone(phone)
    if not ph or not code:
        return False, "Phone and 6-digit OTP code are required"

    code_clean = str(code).strip()
    if len(code_clean) != 6 or not code_clean.isdigit():
        return False, "OTP must be a 6-digit number"

    with _lock:
        rec = _otps.get(ph)
        if not rec:
            return False, "No active OTP found. Please request a new code."

        if now > rec["exp"]:
            _otps.pop(ph, None)
            return False, "OTP has expired. Please request a new code."

        if rec["attempts"] >= MAX_VERIFY_ATTEMPTS:
            _otps.pop(ph, None)
            return False, "Maximum 3 attempts exceeded. OTP locked. Request a new code."

        expected_hash = rec["hash"]
        actual_hash = _hash_otp(code_clean, rec["salt"])

        if not hmac.compare_digest(expected_hash, actual_hash):
            rec["attempts"] += 1
            remaining = MAX_VERIFY_ATTEMPTS - rec["attempts"]
            if remaining <= 0:
                _otps.pop(ph, None)
                return False, "Wrong OTP. Maximum attempts exceeded. Code locked."
            return False, f"Invalid OTP code. {remaining} attempt(s) remaining."

        # Success - clean up OTP
        _otps.pop(ph, None)
        return True, "Verification successful"


def clear_otps() -> None:
    """Test helper to clear memory state."""
    with _lock:
        _otps.clear()
        _req_history.clear()

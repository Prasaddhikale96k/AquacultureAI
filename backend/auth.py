"""Farmer phone verification via SMS OTP (free SMSGate/textbee chain).

Advisory system, no hardware control. OTPs are hashed in the optional audit
log, never stored in plaintext and never returned by the API. Verified numbers
are added to the alert recipient list automatically; full numbers are local PII
and are never exposed through the API.

Env:
  AQUA_AUTH_SECRET   optional HMAC secret for session tokens
  AQUA_OTP_TTL_S     default 300
  AQUA_OTP_WAIT_S    default 60 (per-phone resend cooldown)
  AQUA_OTP_PER_HOUR  default 5
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from backend import alerts

MAX_FILE_BYTES = 20 * 1024 * 1024
_lock = threading.RLock()
_pending = {}       # normalized phone -> {hash, exp, tries, t}
_req_times = {}     # normalized phone -> [timestamps]
_secret = os.environ.get("AQUA_AUTH_SECRET") or secrets.token_hex(32)


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[1] / "backend" / "data"))


def _otp_file():
    return _data_dir() / "otp_log.jsonl"


def _verified_file():
    return _data_dir() / "verified_phones.jsonl"


def _append(path, rec):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > MAX_FILE_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
        with _lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _env_int(name, default):
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


def ttl_s():
    return max(60, _env_int("AQUA_OTP_TTL_S", 300))


def normalize_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        digits = "91" + digits
    if not (10 <= len(digits) <= 15):
        return None
    return "+" + digits


def mask(phone):
    digits = re.sub(r"\D", "", phone or "")
    return "***" + digits[-3:] if digits else None


def _hash(phone, code):
    return hmac.new(_secret.encode(), f"{phone}|{code}".encode(), hashlib.sha256).hexdigest()


def _token(phone, now):
    exp = int(now + 7 * 86400)
    payload = f"{phone}|{exp}"
    sig = hmac.new(_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def verified_phones(days=60):
    """Return normalized phones currently subscribed to SMS alerts.

    A phone is subscribed if its latest event (within the window) is "verified"
    and it has not been subsequently "removed". Events are processed in file
    order so a later remove overrides an earlier verify.
    """
    try:
        p = _verified_file()
        if not p.is_file():
            return []
        cutoff = time.time() - days * 86400
        state: dict[str, bool] = {}
        for line in p.read_text(encoding="utf-8").splitlines()[-5000:]:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ph, t = r.get("phone"), r.get("t")
            event = r.get("event", "verified")
            if not isinstance(ph, str) or not isinstance(t, (int, float)) or t < cutoff:
                continue
            if event == "removed":
                state[ph] = False
            elif event == "verified":
                state[ph] = True
        return [ph for ph, subscribed in state.items() if subscribed]
    except OSError:
        return []


def unverify_phone(phone, now=None):
    """Remove a normalized phone from the alert recipient list.
    Accepts either a full normalized number or a masked format (***last3).
    If masked and exactly one verified phone matches, that phone is removed."""
    raw = str(phone or "").strip()
    ph = normalize_phone(raw)
    if ph:
        now = time.time() if now is None else float(now)
        _append(_verified_file(), {"t": now, "event": "removed", "phone": ph})
        return True
    # Try masked match: extract last 3 digits and find unique verified match
    digits_only = re.sub(r"[^\d]", "", raw)
    if digits_only and len(digits_only) >= 3:
        last_three = digits_only[-3:]
        candidates = []
        try:
            for verified in verified_phones(days=9999):
                v_digits = re.sub(r"\D", "", verified)
                if len(v_digits) >= 3 and v_digits[-3:] == last_three:
                    candidates.append(verified)
        except Exception:
            pass
        if len(candidates) == 1:
            ph = candidates[0]
            now = time.time() if now is None else float(now)
            _append(_verified_file(), {"t": now, "event": "removed", "phone": ph})
            return True
    return False


def mark_verified(phone, now=None):
    """Add a normalized phone to the alert recipient list after OTP verification."""
    ph = normalize_phone(phone)
    if not ph:
        return False
    now = time.time() if now is None else float(now)
    _append(_verified_file(), {"t": now, "event": "verified", "phone": ph})
    return True


def request_otp(phone, now=None):
    """Send a 6-digit OTP. The code is never returned or logged in plaintext."""
    now = time.time() if now is None else float(now)
    ph = normalize_phone(phone)
    if not ph:
        return {"ok": False, "sent": False, "reason": "invalid phone number"}
    with _lock:
        times = [t for t in _req_times.get(ph, []) if now - t < 3600]
        if times and now - times[-1] < max(10, _env_int("AQUA_OTP_WAIT_S", 60)):
            return {"ok": False, "sent": False, "reason": "please wait before requesting another OTP",
                    "phone_masked": mask(ph)}
        if len(times) >= max(1, _env_int("AQUA_OTP_PER_HOUR", 5)):
            return {"ok": False, "sent": False, "reason": "too many OTP requests; try later",
                    "phone_masked": mask(ph)}
        code = str(secrets.randbelow(900000) + 100000)
        _pending[ph] = {"hash": _hash(ph, code), "exp": now + ttl_s(), "tries": 0, "t": now}
        _req_times[ph] = times + [now]
    msg = f"AquaAI OTP: {code}. Use within {ttl_s() // 60} min. Do not share it. -AquaAI"
    res = alerts.send_alert("OTP", msg, "INFO", now=now, force=True, phones=[ph],
                            log_message="OTP sent (code redacted)")
    _append(_otp_file(), {"ts": res.get("id"), "t": now, "event": "otp_request",
                          "phone_masked": mask(ph), "delivered": res["delivered"],
                          "statuses": res["statuses"]})
    out = {"ok": bool(res["delivered"]), "sent": bool(res["delivered"]),
           "phone_masked": mask(ph), "expires_in_s": ttl_s(),
           "providers": res["providers"], "statuses": res["statuses"]}
    if not res["delivered"]:
        with _lock:
            _pending.pop(ph, None)
        out["reason"] = ("no SMS provider configured" if not alerts.configured_providers()
                         else "SMS delivery failed; check gateway/device")
    return out


def verify_otp(phone, code, now=None):
    now = time.time() if now is None else float(now)
    ph = normalize_phone(phone)
    if not ph or not code:
        return {"ok": False, "reason": "phone and code required"}
    with _lock:
        rec = _pending.get(ph)
        if not rec:
            return {"ok": False, "reason": "no active OTP; request a new one"}
        if now > rec["exp"]:
            _pending.pop(ph, None)
            return {"ok": False, "reason": "OTP expired; request a new one"}
        rec["tries"] += 1
        if rec["tries"] > 5:
            _pending.pop(ph, None)
            return {"ok": False, "reason": "too many attempts; request a new OTP"}
        good = hmac.compare_digest(rec["hash"], _hash(ph, str(code).strip()))
        if not good:
            _append(_otp_file(), {"t": now, "event": "otp_verify", "phone_masked": mask(ph), "ok": False})
            return {"ok": False, "reason": "wrong OTP"}
        _pending.pop(ph, None)
        mark_verified(ph, now)
        _append(_otp_file(), {"t": now, "event": "otp_verify", "phone_masked": mask(ph), "ok": True})
    return {"ok": True, "phone_masked": mask(ph), "token": _token(ph, now),
            "verified": True, "alerts_enabled": True}


def status():
    return {"enabled": bool(alerts.configured_providers()),
            "providers_configured": {p: alerts.provider_configured(p)
                                     for p in ("textbee", "smsgate", "gammu")},
            "otp_ttl_s": ttl_s(),
            "verified_count": len(verified_phones()),
            "verified_masked": [mask(p) for p in verified_phones()],
            "note": "Phone verification enables SMS alerts to that number. OTP codes are never logged."}

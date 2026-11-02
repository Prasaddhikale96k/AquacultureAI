"""Farmer alert engine: rule evaluation, free SMS via textbee, append-only log.

Design rules (farmer-grade finalization, B):
- v1 is ADVISORY ONLY. Nothing here talks to pumps, feeders, relays or any
  hardware. RAS main pump is life-support and must stay 24x7.
- Every alert attempt is appended to backend/data/alert_log.jsonl with masked
  phones only. API keys are never written or returned.
- `log` is always part of the provider chain, so rule firings are recorded even
  when SMS is not configured. Free adapters: textbee (TEXTBEE_API_KEY +
  TEXTBEE_DEVICE_ID), SMSGate (SMSGATE_URL, farm LAN) and Gammu
  (GAMMU_URL). Only configured adapters are attempted, in env order; the first
  success stops failover.
- Rules R1-R6 are PROVISIONAL: thresholds are env-overridable and labelled as
  such in the message context. Turbidity thresholds act on the sensor's RAW ADC
  value because no NTU calibration exists.
- R1 stale feed, R2 temp outside 22-34 C for 10 min, R3 >2 C/h,
    R4 turbidity >+40% vs trailing 6 h median, R5 dawn-DO advisory at 04:30,
    R6 sustained behaviour anomaly (15 min), R7 estimated DO in the risk or
    critical band after 2 consecutive evaluations, R8 fish-behaviour hypoxia
    suspect (EMERGENCY: fires immediately on transition, no cooldown gate),
    R9 weak feeding response (2 in a row). Messages are plain English ASCII
    <=160.

Endpoints (main.py): GET /api/alerts, POST /api/alerts/test,
POST /api/alerts/false-alarm, GET /api/dashboard.
"""
import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend import sensors

MAX_FILE_BYTES = 50 * 1024 * 1024
RULE_LABELS = {
    "R1": "sensor data stopped", "R2": "water temp out of range",
    "R3": "rapid temp change", "R4": "turbidity rising fast",
    "R5": "dawn DO risk", "R6": "behaviour anomaly",
    "R7": "dissolved oxygen low", "R8": "fish behaviour hypoxia suspect",
    "R9": "weak feeding response",
}
COOLDOWN_MIN = {"R1": 240, "R2": 60, "R3": 60, "R4": 60, "R5": 1440, "R6": 120,
                "R7": 60, "R8": 60, "R9": 1440, "DIGEST": 1440}
RULE_POINTS = {"R1": 40, "R2": 40, "R3": 20, "R4": 20, "R5": 15, "R6": 10,
               "R7": 15, "R8": 0, "R9": 0}
DEFAULT_PROVIDERS = "textbee,log"
MAX_MESSAGE = 160

_lock = threading.RLock()
_last_sent = {}
_prev_active = set()
_loaded = False
_settings = {}
_settings_loaded = False
_thread = None
_stop = threading.Event()
_do_last_level = None
_do_streak = 0


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[1] / "backend" / "data"))


def _file():
    return _data_dir() / "alert_log.jsonl"


def _settings_file():
    return _data_dir() / "alert_settings.json"


def _rotate(p, max_bytes=MAX_FILE_BYTES):
    try:
        if p.is_file() and p.stat().st_size > max_bytes:
            p.replace(p.with_suffix(p.suffix + ".1"))
    except OSError:
        pass


def _env_float(name, default):
    try:
        v = float(os.environ.get(name, ""))
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _env_int(name, default):
    try:
        return int(float(os.environ.get(name, "")))
    except (TypeError, ValueError):
        return int(default)


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _now(now=None):
    return time.time() if now is None else float(now)


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


# ---------------------------------------------------------------- providers
def phone_list():
    raw = os.environ.get("AQUA_ALERT_PHONES", "")
    out = []
    for p in re.split(r"[,;]", raw):
        digits = re.sub(r"[^\d+]", "", p.strip())
        if re.match(r"^\+?\d{8,15}$", digits):
            out.append(digits)
    try:
        from backend import auth
        for p in auth.verified_phones():
            if p not in out:
                out.append(p)
    except Exception:
        pass
    return out


def mask(phone):
    digits = re.sub(r"\D", "", phone or "")
    return "***" + digits[-3:] if digits else None


def provider_order():
    raw = os.environ.get("AQUA_ALERT_PROVIDERS", DEFAULT_PROVIDERS)
    known = []
    for p in re.split(r"[,;]", raw):
        p = p.strip().lower()
        if p in ("textbee", "smsgate", "gammu", "log") and p not in known:
            known.append(p)
    if "log" not in known:
        known.append("log")
    return known or ["log"]


def textbee_config():
    return {
        "base_url": (os.environ.get("TEXTBEE_BASE_URL") or "https://api.textbee.dev").rstrip("/"),
        "api_key": os.environ.get("TEXTBEE_API_KEY", "").strip(),
        "device_id": os.environ.get("TEXTBEE_DEVICE_ID", "").strip(),
    }


def textbee_configured():
    c = textbee_config()
    return bool(c["api_key"] and c["device_id"])


def smsgate_config():
    return {"base_url": (os.environ.get("SMSGATE_URL") or "https://api.sms-gate.app/3rdparty/v1").rstrip("/"),
            "username": os.environ.get("SMSGATE_USERNAME", "").strip(),
            "password": os.environ.get("SMSGATE_PASSWORD", ""),
            "token": os.environ.get("SMSGATE_TOKEN", "").strip(),
            "device_id": os.environ.get("SMSGATE_DEVICE_ID", "").strip()}


def gammu_config():
    return {"base_url": (os.environ.get("GAMMU_URL") or "").rstrip("/"),
            "token": os.environ.get("GAMMU_TOKEN", "").strip()}


def smsgate_configured():
    c = smsgate_config()
    return bool(c["base_url"] and ((c["username"] and c["password"]) or c["token"]))


def gammu_configured():
    return bool(gammu_config()["base_url"])


def provider_configured(provider):
    return {"textbee": textbee_configured, "smsgate": smsgate_configured,
            "gammu": gammu_configured}.get(provider, lambda: False)()


def configured_providers():
    return [p for p in provider_order() if p != "log" and provider_configured(p)]


def dry_run():
    return _env_flag("AQUA_ALERT_TEST", False)


def _call_once(provider, phone, message, timeout):
    """One HTTP call. Returns (http_code, status, error); never raises."""
    if provider == "textbee":
        c = textbee_config()
        body = json.dumps({"phoneNumber": phone, "message": message,
                           "deviceId": c["device_id"]}).encode("utf-8")
        req = urllib.request.Request(f"{c['base_url']}/v1/sms/send", data=body, method="POST", headers={
            "Content-Type": "application/json", "x-api-key": c["api_key"],
            "User-Agent": "AquaCultureAI/1.0"})
    elif provider == "smsgate":
        c = smsgate_config()
        payload = {"textMessage": {"text": message}, "phoneNumbers": [phone]}
        if c["device_id"]:
            payload["deviceId"] = c["device_id"]
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "AquaCultureAI/1.0"}
        if c["username"] and c["password"]:
            token = base64.b64encode(f"{c['username']}:{c['password']}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        elif c["token"]:
            headers["Authorization"] = f"Bearer {c['token']}"
        req = urllib.request.Request(f"{c['base_url']}/messages", data=body, method="POST", headers=headers)
    else:
        c = gammu_config()
        body = json.dumps({"to": phone, "text": message}).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "AquaCultureAI/1.0"}
        if c["token"]:
            headers["Authorization"] = f"Bearer {c['token']}"
        req = urllib.request.Request(f"{c['base_url']}/sms", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = getattr(r, "status", None)
            r.read(2048)
        return code, ("sent" if (code or 0) < 300 else "failed"), None
    except urllib.error.HTTPError as e:
        return e.code, "failed", f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, "failed", f"{type(e).__name__}"


def _attempt(provider, phone, message, timeout=10):
    """One provider attempt. Returns an attempt dict; never raises, never logs secrets."""
    t0 = time.perf_counter()
    rec = {"provider": provider, "status": "failed", "phone_masked": mask(phone) if phone else None,
           "http_code": None, "latency_ms": None, "error": None}
    try:
        if provider not in ("textbee", "smsgate", "gammu"):
            rec["status"] = "logged"
        elif not provider_configured(provider):
            rec["status"] = "skipped_no_config"
            rec["error"] = "provider not configured"
        elif dry_run():
            rec["status"] = "dry_run"
        else:
            last = None
            for i in range(2):
                code, status, err = _call_once(provider, phone, message, timeout)
                rec["http_code"], rec["status"], last = code, status, err
                if status == "sent":
                    break
                if code is not None and 400 <= code < 500 and code != 429:
                    break                      # permanent client error: do not retry
                if i == 0:
                    time.sleep(1.5)
            if last:
                rec["error"] = last
    except Exception as e:  # noqa: BLE001 - provider issues must never break rules
        rec["error"] = f"{type(e).__name__}"
    rec["latency_ms"] = round((time.perf_counter() - t0) * 1000)
    return rec


def _append(rec):
    try:
        p = _file()
        p.parent.mkdir(parents=True, exist_ok=True)
        _rotate(p)
        with _lock:
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _load_state():
    """Restore cooldowns from the log so a restart cannot spam the owner."""
    global _loaded
    with _lock:
        if _loaded:
            return
        try:
            p = _file()
            if p.is_file():
                for line in p.read_text(encoding="utf-8").splitlines()[-5000:]:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("event") == "alert" and r.get("rule") in COOLDOWN_MIN:
                        t = r.get("t")
                        if isinstance(t, (int, float)):
                            _last_sent[r["rule"]] = max(_last_sent.get(r["rule"], 0), t)
        except OSError:
            pass
        _loaded = True


def _load_settings():
    """Load user-configurable alert settings (cooldown overrides) from JSON."""
    global _settings, _settings_loaded
    with _lock:
        if _settings_loaded:
            return _settings
        try:
            p = _settings_file()
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    overrides = data.get("cooldown_min", {})
                    if isinstance(overrides, dict):
                        _settings = {str(k): int(v) for k, v in overrides.items()
                                     if isinstance(v, (int, float))}
        except (OSError, ValueError):
            _settings = {}
        _settings_loaded = True
        return _settings


def _save_settings():
    """Persist current cooldown overrides to the JSON settings file."""
    try:
        p = _settings_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with p.open("w", encoding="utf-8") as f:
                json.dump({"cooldown_min": dict(_settings)}, f, ensure_ascii=False)
    except OSError:
        pass


def get_alert_settings():
    """Return effective cooldown minutes per rule (user override wins)."""
    _load_state()
    _load_settings()
    out = {}
    for rule in COOLDOWN_MIN:
        out[rule] = _cooldown_minutes(rule)
    return out


def set_alert_settings(updates):
    """Apply cooldown-minute overrides for the given rules and persist."""
    _load_settings()
    with _lock:
        changed = False
        for rule, minutes in (updates or {}).items():
            if rule in COOLDOWN_MIN and isinstance(minutes, (int, float)):
                minutes = int(minutes)
                if minutes < 1:
                    minutes = 1
                if _settings.get(rule) != minutes:
                    _settings[rule] = minutes
                    changed = True
        if changed:
            _save_settings()
    return get_alert_settings()


def _cooldown_minutes(rule):
    # Explicit env override wins (keeps R8 operator-tunable), then user
    # settings, then the compiled-in default.
    if rule == "R8":
        raw = os.environ.get("AQUA_BEH_SMS_REPEAT_MIN", "")
        if raw.strip():
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                pass
    with _lock:
        user = _settings.get(rule)
    if user is not None:
        return user
    return COOLDOWN_MIN.get(rule, 60)


def _in_cooldown(rule, now):
    until = _last_sent.get(rule, 0) + _cooldown_minutes(rule) * 60
    return now < until


def send_alert(rule, message, level="HIGH", now=None, force=False, phones=None,
               log_message=None, sms=True, max_len=MAX_MESSAGE):
    """Send one alert through the provider chain and append the audit log.

    Returns a dict with `delivered` (at least one textbee `sent`),
    `attempts`, `logged` and `cooldown_min`. Cooldown is set for real rules
    even when SMS is unconfigured: the log is the delivery channel then.
    `sms=False` records the alert without contacting any provider.
    `max_len` defaults to one SMS (160); the daily digest opts into 300.
    """
    _load_state()
    now = _now(now)
    limit = max(1, min(300, int(max_len)))
    message = (message or "")[:limit]
    phones = [] if not sms else (list(phones) if phones is not None else phone_list())
    order = provider_order()
    attempts = []
    with _lock:
        delivered = False
        if sms:
            for provider in order:
                if provider == "log":
                    continue
                if not phones:
                    attempts.append({"provider": provider, "status": "skipped_no_config",
                                     "phone_masked": None, "http_code": None, "latency_ms": 0,
                                     "error": "AQUA_ALERT_PHONES is empty"})
                    continue
                if not provider_configured(provider):
                    attempts.append({"provider": provider, "status": "skipped_no_config",
                                     "phone_masked": None, "http_code": None, "latency_ms": 0,
                                     "error": "provider not configured"})
                    continue
                for phone in phones:
                    a = _attempt(provider, phone, message)
                    attempts.append(a)
                    delivered = delivered or a["status"] == "sent"
                if delivered:
                    break                  # ordered failover: stop after first success
        attempts.append({"provider": "log", "status": "logged", "phone_masked": None,
                         "http_code": None, "latency_ms": 0, "error": None})
        alert_id = uuid.uuid4().hex[:12]
        summary = {"ts": _iso(now), "t": now, "event": "alert", "id": alert_id, "rule": rule,
                   "level": level,                    "message": (log_message or message)[:limit],
                   "delivered": delivered, "providers": [a["provider"] for a in attempts],
                   "statuses": [a["status"] for a in attempts],
                   "phones_masked": [mask(p) for p in phones]}
        _append(summary)
        for a in attempts:
            _append({"ts": _iso(now), "t": now, "event": "attempt", "ref": alert_id,
                     "rule": rule, "level": level, **a})
        if rule in COOLDOWN_MIN and not force:
            _last_sent[rule] = now
    return {"id": alert_id, "rule": rule, "level": level, "delivered": delivered,
            "attempts": attempts, "statuses": [a["status"] for a in attempts],
            "providers": [a["provider"] for a in attempts],
            "logged": True, "cooldown_min": _cooldown_minutes(rule),
            "textbee_configured": textbee_configured(), "dry_run": dry_run(),
            "phones_masked": [mask(p) for p in phones]}


# ---------------------------------------------------------------- rules
def _temp_max():
    return _env_float("AQUA_TEMP_MAX_C", 34.0)


def _temp_min():
    return _env_float("AQUA_TEMP_MIN_C", 22.0)


def _turb_rise_pct():
    return _env_float("AQUA_TURB_RISE_PCT", 40.0)


def _temp_swing_c():
    return _env_float("AQUA_TEMP_SWING_C", 2.0)


def _stale_s():
    return _env_float("AQUA_STALE_ALERT_MIN", 0.0) * 60


def _tank():
    return (os.environ.get("AQUA_TANK_NAME") or "Tank").strip() or "Tank"


def _fresh(row, now):
    return row is not None and isinstance(row.get("t"), (int, float)) and now - row["t"] <= _stale_s()


def _median(vals):
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    return vals[len(vals) // 2]


def current_rules(now=None):
    """Evaluate R1-R6 without sending. Each item: rule, level, message, evidence."""
    now = _now(now)
    out = []
    latest = sensors.latest()
    fresh = _fresh(latest, now)
    temp = latest.get("temperature") if fresh else None
    tank = _tank()

    # R1 CRITICAL: sensor feed missing/stale (repeat every 4 h, resolved note follows)
    if not fresh:
        stale_min = int(max(0, now - latest["t"]) / 60) if latest and isinstance(latest.get("t"), (int, float)) else None
        if stale_min is None:
            msg = f"ALERT R1: {tank} sensor data has not started. Check power/internet! -AquaAI"
        else:
            msg = (f"ALERT R1: {tank} sensor data stopped {stale_min} min ago. "
                   "Check power/pump/internet! -AquaAI")
        out.append({"rule": "R1", "level": "CRITICAL", "metric": "sensor_age",
                    "value": stale_min, "threshold": _stale_s() / 60, "message": msg})

    if temp is not None:
        mx, mn = _temp_max(), _temp_min()
        rows = [r for r in sensors.recent(60) if isinstance(r.get("temperature"), (int, float))]
        win = [r for r in rows if now - 10 * 60 <= r["t"] <= now]
        if len(win) >= 2 and now - min(r["t"] for r in win) >= 8 * 60:
            vals = [r["temperature"] for r in win]
            if all(v > mx for v in vals) or all(v < mn for v in vals):
                out.append({"rule": "R2", "level": "CRITICAL", "metric": "temperature",
                            "value": round(temp, 2), "threshold": [mn, mx], "sustained_min": 10,
                            "message": (f"ALERT R2: Water temp {temp:.1f}C outside safe range "
                                        f"({mn:.0f}-{mx:.0f}). Check now! -AquaAI")})
        ref = None
        for r in [x for x in sensors.recent(90) if isinstance(x.get("temperature"), (int, float))]:
            age = now - r["t"]
            if 45 * 60 <= age <= 75 * 60:
                if ref is None or abs(age - 3600) < abs((now - ref["t"]) - 3600):
                    ref = r
        if ref is not None:
            delta = temp - ref["temperature"]
            if abs(delta) >= _temp_swing_c():
                out.append({"rule": "R3", "level": "HIGH", "metric": "temperature",
                            "value": round(delta, 2), "threshold": _temp_swing_c(),
                            "message": (f"ALERT R3: Water temp changed {delta:+.1f}C in 1 hour. "
                                        "Check aeration! -AquaAI")})

    # R4 HIGH: turbidity > +40% vs trailing 6 h median, within the last hour
    turb_rows = [r for r in sensors.recent(360) if isinstance(r.get("turbidity"), (int, float))]
    recent_t = [r["turbidity"] for r in turb_rows if now - 60 * 60 <= r["t"] <= now]
    base_t = [r["turbidity"] for r in turb_rows if now - 360 * 60 <= r["t"] < now - 60 * 60]
    if recent_t and len(base_t) >= 3:
        lastv = recent_t[-1]
        base = _median(base_t)
        pct = (lastv - base) / max(1.0, abs(base)) * 100 if base is not None else 0.0
        if pct >= _turb_rise_pct():
            out.append({"rule": "R4", "level": "HIGH", "metric": "turbidity",
                        "value": round(lastv, 1), "threshold": _turb_rise_pct(),
                        "rise_pct": round(pct, 1),
                        "message": (f"ALERT R4: Turbidity rose {pct:+.0f}% in 1 hour. "
                                    "Check water/filter! -AquaAI")})

    # R5 MEDIUM/HIGH: daily dawn-DO advisory at 04:30 local (one per day via cooldown)
    try:
        from backend import predict
        local = datetime.fromtimestamp(now)
        if local.hour == 4 and local.minute >= 30:
            risk = predict.dawn_risk(now=now)
            if risk.get("level") in ("LOW", "MEDIUM", "HIGH"):
                lvl = {"LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH"}[risk["level"]]
                out.append({"rule": "R5", "level": lvl, "metric": "dawn_risk",
                            "value": risk.get("score"), "threshold": 0.65,
                            "message": (f"ALERT R5: Dawn DO crash risk {lvl} "
                                        f"({float(risk.get('score') or 0):.2f}). Keep blower on; "
                                        "pump 24x7. -AquaAI")})
    except Exception:
        pass
    try:
        from backend import behavior_stats
        b = behavior_stats.current_anomaly(now=now)
        if b and b.get("sustained"):
            out.append({"rule": "R6", "level": "MEDIUM", "metric": b.get("metric"),
                        "value": b.get("z"), "threshold": 3,
                        "message": (f"ALERT R6: {tank} fish behaviour {b.get('metric')} abnormal "
                                    f"15+ min (z={float(b.get('z') or 0):.1f}). Check aeration/water! -AquaAI")})
    except Exception:
        pass
    if _env_flag("AQUA_DO_ALERT", True):
        try:
            from backend.app.services import do_service
            p = do_service.prediction(now=now)
            if p.get("status") == "ok" and p.get("risk_level") in ("watch", "risk", "critical"):
                do = float(p.get("do_mgl") or 0.0)
                crit = _env_float("AQUA_DO_CRIT_MGL", 2.0)
                warn = _env_float("AQUA_DO_WARN_MGL", 3.5)
                ev = p.get("behaviour_evidence") or {}
                suffix = (f" Camera: {int(ev.get('sustained_min') or 0)} min suspect."
                          if ev.get("state") == "hypoxia_suspect" else "")
                if p["risk_level"] == "critical":
                    msg = (f"AquaAI DO CRITICAL: Estimated DO {do:.1f} mg/L (<{crit:g}). "
                           f"Check aeration/blower now, exchange water. Fish at risk!{suffix} -AquaAI")
                    out.append({"rule": "R7", "level": "CRITICAL", "metric": "do_mgl",
                                "value": do, "threshold": crit, "message": msg})
                elif p["risk_level"] == "risk":
                    msg = (f"AquaAI DO RISK: Estimated DO {do:.1f} mg/L. "
                           f"Check aeration, reduce feeding, watch at dawn.{suffix} -AquaAI")
                    out.append({"rule": "R7", "level": "HIGH", "metric": "do_mgl",
                                "value": do, "threshold": warn, "message": msg})
                else:
                    # watch level: MEDIUM, contributes to khatra
                    msg = (f"AquaAI DO WATCH: Estimated DO {do:.1f} mg/L. "
                           f"Keep aeration on, monitor at dawn.{suffix} -AquaAI")
                    out.append({"rule": "R7", "level": "MEDIUM", "metric": "do_mgl",
                                "value": do, "threshold": warn, "message": msg})
        except Exception:
            pass
    if _env_flag("AQUA_BEH_ALERT", True):
        try:
            from backend.app.services import behaviour_service
            ev = behaviour_service.evidence(now=now)
            if ev:
                out.append({"rule": "R8", "level": "CRITICAL", "metric": "hbs",
                            "value": ev.get("hbs"), "threshold": behaviour_service.threshold(),
                            "message": behaviour_service.behaviour_message(ev.get("sustained_min") or 15)})
        except Exception:
            pass
    return out


def evaluate(now=None, send=True):
    """Evaluate rules, send due alerts, and send one resolved note per recovery."""
    global _prev_active, _do_last_level, _do_streak
    _load_state()
    now = _now(now)
    rules = {r["rule"]: r for r in current_rules(now)}
    if "R7" in rules:
        level = rules["R7"]["level"]
        if level == _do_last_level:
            _do_streak += 1
        else:
            _do_last_level, _do_streak = level, 1
        if _do_streak < 2:
            rules.pop("R7", None)
    else:
        _do_last_level, _do_streak = None, 0
    if not send:
        return list(rules.values())
    sent = []
    for rule, info in rules.items():
        # R8 (fish-behaviour hypoxia suspect) is an EMERGENCY: fire
        # immediately on the transition into the suspect state, with NO
        # cooldown gate. The camera path in behaviour_service also fires it
        # on transition and marks _prev_active so this loop does not
        # double-fire. While the suspect state persists, R8 is not repeated
        # by this loop (it stays in _prev_active); only a fresh transition
        # (or a restart with the state already suspect) triggers it again.
        if rule == "R8":
            if rule not in _prev_active:
                sent.append(send_alert(rule, info["message"], info["level"], now=now, sms=True))
            continue
        if not _in_cooldown(rule, now):
            sms = rule != "R7" or info["level"] == "CRITICAL"
            sent.append(send_alert(rule, info["message"], info["level"], now=now, sms=sms))
    for rule in sorted(_prev_active - set(rules)):
        if rule in RULE_LABELS and now >= _last_sent.get(rule + "_RESOLVED", 0) + 3600:
            msg = (f"RESOLVED {rule}: {RULE_LABELS[rule]} is normal again. "
                   "Keep monitoring. -AquaAI")
            sent.append(send_alert(rule + "_RESOLVED", msg, "INFO", now=now))
            _last_sent[rule + "_RESOLVED"] = now
    _prev_active = set(rules)
    return sent


def khatra(rules=None, now=None):
    """Farmer-facing 0-100 risk score with the R1-R6 weights (E)."""
    rules = current_rules(now=now) if rules is None else rules
    score = 0
    for r in rules:
        if r["rule"] in ("R1", "R2", "R3", "R4"):
            score += RULE_POINTS[r["rule"]]
        elif r["rule"] == "R5" and r.get("level") == "HIGH":
            score += RULE_POINTS["R5"]
        elif r["rule"] == "R6":
            score += RULE_POINTS["R6"]
        elif r["rule"] == "R7":
            score += RULE_POINTS["R7"]
    score = max(0, min(100, score))
    level = "LOW" if score < 35 else "MEDIUM" if score < 65 else "HIGH"
    return {"score": score, "level": level, "active": rules,
            "weights": RULE_POINTS,
            "note": "PROVISIONAL: weights are project defaults, not validated risk odds."}


# ---------------------------------------------------------------- log + test
def _read_log(limit=4000):
    try:
        p = _file()
        if not p.is_file():
            return []
        lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
            if isinstance(r, dict):
                out.append(r)
        except ValueError:
            continue
    return out


def recent(limit=50):
    rows = [r for r in _read_log() if r.get("event") == "alert"]
    rows.sort(key=lambda r: r.get("t", 0), reverse=True)
    return rows[:max(1, min(int(limit), 200))]


def false_alarm_ids():
    return {r.get("ref") for r in _read_log() if r.get("event") == "false_alarm"}


def mark_false_alarm(alert_id, note=None):
    _load_state()
    rows = [r for r in _read_log() if r.get("event") == "alert" and r.get("id") == alert_id]
    if not rows:
        return None
    rec = {"ts": _iso(time.time()), "t": time.time(), "event": "false_alarm",
           "ref": alert_id, "note": (note or "")[:200]}
    _append(rec)
    return rec


def test_alert(now=None):
    """POST /api/alerts/test: one real SMS when configured; honest dry-run otherwise."""
    msg = (f"AquaAI TEST SMS ({datetime.now().strftime('%d-%m %H:%M')}). "
           "Koi action zaroori nahi. Main pump 24x7. -AquaAI")
    res = send_alert("TEST", msg, "INFO", now=now, force=True)
    res["textbee_configured"] = textbee_configured()
    res["phones_configured"] = len(phone_list())
    res["providers_configured"] = configured_providers()
    if not phone_list():
        res["reason"] = "AQUA_ALERT_PHONES is empty"
    elif not configured_providers():
        res["reason"] = "No SMS provider configured (textbee/smsgate/gammu)"
    elif dry_run():
        res["reason"] = "AQUA_ALERT_TEST=1 (dry run; no SMS sent)"
    res["ok"] = bool(res["delivered"])
    return res


def _provider_status():
    """Latest attempt per provider, for the dashboard (no phones/keys)."""
    out = {}
    for r in reversed(_read_log()):
        if r.get("event") != "attempt":
            continue
        p = r.get("provider")
        if p and p not in out:
            out[p] = {"ts": r.get("ts"), "status": r.get("status"),
                      "http_code": r.get("http_code"), "latency_ms": r.get("latency_ms")}
    return out


def config_summary():
    c = textbee_config()
    return {"providers": provider_order(), "textbee_configured": textbee_configured(),
            "textbee_base_url": c["base_url"], "phones_masked": [mask(p) for p in phone_list()],
            "phones_configured": len(phone_list()), "dry_run": dry_run(), "tank": _tank(),
            "providers_configured": {p: provider_configured(p) for p in ("textbee", "smsgate", "gammu")},
            "provider_status": _provider_status(),
            "stale_alert_min": _stale_s() / 60,
            "rules": {k: {"label": v, "cooldown_min": _cooldown_minutes(k), "points": RULE_POINTS.get(k, 0)}
                      for k, v in RULE_LABELS.items()}}


# ---------------------------------------------------------------- digest
def digest_payload(now=None):
    now = _now(now)
    week = [r for r in _read_log() if r.get("event") == "alert" and now - (r.get("t") or 0) <= 7 * 86400]
    false_ids = false_alarm_ids()
    real = [r for r in week if r.get("id") not in false_ids and r.get("rule") not in ("TEST", "DIGEST")]
    by_rule = {}
    for r in real:
        by_rule[r.get("rule")] = by_rule.get(r.get("rule"), 0) + 1
    top = max(by_rule, key=by_rule.get) if by_rule else None
    false_count = sum(1 for r in week if r.get("id") in false_ids)
    return {"window_days": 7, "alerts": len(real), "test_messages": sum(1 for r in week if r.get("rule") == "TEST"),
            "false_alarms": false_count, "by_rule": by_rule,
            "top_rule": RULE_LABELS.get(top, top), "uptime_pct": sensors.stats(7 * 24)["uptime_pct"],
            "delivered": sum(1 for r in real if r.get("delivered"))}


def weekly_digest(now=None):
    now = _now(now)
    d = digest_payload(now)
    msg = (f"AquaAI weekly: {d['alerts']} alerts, {d['false_alarms']} false, "
           f"uptime {d['uptime_pct']:.0f}%."
           + (f" Top: {d['top_rule']}." if d["top_rule"] else "")
           + " Main pump 24x7. -AquaAI")
    r = send_alert("DIGEST", msg, "INFO", now=now, force=True)
    r["digest"] = d
    return r


def _last_digest_day():
    for r in reversed(_read_log()):
        if r.get("event") == "alert" and r.get("rule") == "DIGEST":
            return datetime.fromtimestamp(r.get("t", 0)).date()
    return None


# ---------------------------------------------------------------- scheduler
def _eval_loop():
    while not _stop.is_set():
        try:
            evaluate()
            from backend.app.services import digest_service, backup_service, feeding_service
            feeding_service.update_responses()
            digest_service.maybe_send()
            backup_service.maybe_backup()
            now = datetime.now()
            if now.weekday() == 6 and now.hour == 18 and now.minute < 3 and _last_digest_day() != now.date():
                weekly_digest()
        except Exception:
            pass
        _stop.wait(max(15, int(_env_float("AQUA_ALERT_EVAL_S", 60))))


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_eval_loop, name="aqua-alerts", daemon=True)
    _thread.start()


def stop():
    _stop.set()

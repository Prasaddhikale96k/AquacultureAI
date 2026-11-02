"""Daily farm digest SMS at a farm-local time (Track IV F3).

One English SMS per farm day, <=300 chars, sent through the existing alert
chain. It is gated by AQUA_DIGEST (default on) and deduped with a small state
file. When sensor data is stale, a shorter honest stale variant is sent.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.services import farm_clock

MAX_DIGEST = 300


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[2] / "data"))


def _state_file():
    return _data_dir() / "daily_digest.json"


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def enabled():
    return _env_flag("AQUA_DIGEST", True)


def _target_minutes():
    raw = str(os.environ.get("AQUA_DAILY_SMS_TIME", "07:00")).strip()
    try:
        h, m = raw.split(":", 1)
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except (TypeError, ValueError):
        pass
    return 7 * 60


def _state():
    try:
        p = _state_file()
        if p.is_file():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    except (OSError, ValueError):
        pass
    return {}


def _save_state(data):
    try:
        p = _state_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _night_do_min(now):
    """Lowest recorded kit DO in the last 24 h during farm-local night."""
    try:
        from backend.app.services import do_service
        start = now - 86400
        vals = []
        for r in do_service.read_readings():
            t = r.get("measured_t")
            v = r.get("value_mgl")
            if not isinstance(t, (int, float)) or not isinstance(v, (int, float)):
                continue
            if t < start:
                continue
            hour = farm_clock.farm_now(t).hour
            if hour >= 20 or hour < 6:
                vals.append(float(v))
        return min(vals) if vals else None
    except Exception:
        return None


def _alerts_24h(now):
    try:
        from backend import alerts
        rows = alerts.recent(3000)
    except Exception:
        return 0
    n = 0
    for r in rows:
        if not isinstance(r, dict) or r.get("event") != "alert":
            continue
        if (r.get("t") or 0) < now - 86400:
            continue
        if str(r.get("rule") or "").endswith("_RESOLVED") or r.get("rule") in ("TEST", "DIGEST"):
            continue
        n += 1
    return n


def build_message(now=None):
    """Return (message, stale). The message is always <=300 characters."""
    now = time.time() if now is None else float(now)
    local = farm_clock.farm_now(now)
    day = local.strftime("%a")
    date = local.strftime("%d %b")
    stale_s = None
    try:
        from backend import sensors
        stale_s = sensors.stats(24).get("stale_s")
    except Exception:
        stale_s = None
    try:
        limit = float(os.environ.get("AQUA_STALE_ALERT_MIN", "20")) * 60.0
    except (TypeError, ValueError):
        limit = 20 * 60.0
    stale = stale_s is None or stale_s > limit
    if stale:
        age = f"{max(0.0, float(stale_s)) / 3600.0:.1f}h" if stale_s is not None else "unknown"
        msg = (f"AquaAI daily digest: sensor data stale {age}. No DO/behaviour summary. "
               "Check ThingSpeak/camera/power. -AquaAI")
        return msg[:MAX_DIGEST], True

    try:
        from backend import alerts
        risk = alerts.khatra(now=now).get("score", 0)
    except Exception:
        risk = 0
    try:
        from backend.app.services import do_service, behaviour_service, feeding_service
        pred = do_service.prediction(now=now)
        behaviour = behaviour_service.summary(now=now).get("state") or "no data"
        do_night = _night_do_min(now)
        if do_night is None:
            do_night = pred.get("do_mgl") if pred.get("status") == "ok" else None
        fed = feeding_service.counts_today(now)
    except Exception:
        do_night, behaviour, fed = None, "no data", 0
    do_txt = f"{do_night:.1f} mg/L" if isinstance(do_night, (int, float)) else "n/a"
    msg = (f"AquaAI {day} {date}: DO {do_txt} at night, behaviour {str(behaviour).replace('_', ' ')}. "
           f"{_alerts_24h(now)} alerts, risk {int(risk)}/100. Feedings today {fed}. "
           "Median wt n/a g, gain n/a g/day. -AquaAI")
    return msg[:MAX_DIGEST], False


def maybe_send(now=None):
    """Send once per farm day when the local clock reaches AQUA_DAILY_SMS_TIME."""
    if not enabled():
        return {"sent": False, "reason": "disabled"}
    now = time.time() if now is None else float(now)
    local = farm_clock.farm_now(now)
    if local.hour * 60 + local.minute < _target_minutes():
        return {"sent": False, "reason": "before send time"}
    day = farm_clock.farm_day(now)
    state = _state()
    if state.get("last_day") == day:
        return {"sent": False, "reason": "already sent today"}
    msg, stale = build_message(now)
    try:
        from backend import alerts
        result = alerts.send_alert("DIGEST", msg, "INFO", now=now, force=True,
                                   sms=True, max_len=MAX_DIGEST)
    except Exception as e:  # noqa: BLE001 - digest must never break the scheduler
        return {"sent": False, "reason": f"{type(e).__name__}", "stale": stale}
    _save_state({"last_day": day, "sent_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                 "stale": stale})
    return {"sent": True, "stale": stale, "message": msg, "result": result}

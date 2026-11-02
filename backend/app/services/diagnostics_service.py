"""Read-only diagnostics snapshot (Track IV F5).

Allow-listed operational state only: no API keys, phone numbers, raw frames,
images, tokens or user records. Safe to expose behind the auth allow-list.
"""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.app.services import farm_clock

_START = time.time()
FLAGS = {
    "AQUA_AUTH_MODE": "full", "AQUA_SCHEDULER": "1",
    "AQUA_DO_PREDICT": "1", "AQUA_DO_ALERT": "1", "AQUA_DO_CAL": "0",
    "AQUA_DO_FEED_DIP": "1", "AQUA_BEH_ALERT": "1", "AQUA_BEH_DO_LINK": "1",
    "AQUA_FEED_LOG": "1", "AQUA_FEED_ALERT": "1", "AQUA_DIGEST": "1",
    "AQUA_BACKUP": "1", "AQUA_EXPORT": "1", "AQUA_TRACK_CONF": "0",
}


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[2] / "data"))


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _effective_flags():
    out = {}
    for name, default in FLAGS.items():
        raw = os.environ.get(name)
        if name in ("AQUA_AUTH_MODE", "AQUA_SCHEDULER"):
            out[name] = (raw if raw is not None else default)
        else:
            out[name] = _env_flag(name, default not in ("0", "false", "no", "off", ""))
    out["AQUA_FARM_TZ"] = os.environ.get("AQUA_FARM_TZ", "Asia/Kolkata")
    out["AQUA_DAILY_SMS_TIME"] = os.environ.get("AQUA_DAILY_SMS_TIME", "07:00")
    return out


def _smsgate_reachable():
    url = os.environ.get("AQUA_SMSGATE_URL", "").strip()
    if not url:
        return None
    try:
        import requests
        r = requests.get(url, timeout=3)
        return {"reachable": True, "http_code": r.status_code}
    except Exception as e:  # noqa: BLE001 - diagnostics must never fail the endpoint
        return {"reachable": False, "error": type(e).__name__}


def _data_stats():
    root = _data_dir()
    files = [p for p in root.iterdir() if p.is_file()] if root.is_dir() else []
    backups = root / "backups"
    last_backup = None
    if backups.is_dir():
        dirs = sorted((d.name for d in backups.iterdir() if d.is_dir()), reverse=True)
        last_backup = dirs[0] if dirs else None
    try:
        du = shutil.disk_usage(str(root))
        disk = {"free_mb": round(du.free / 1024 / 1024), "total_mb": round(du.total / 1024 / 1024)}
    except OSError:
        disk = {"free_mb": None, "total_mb": None}
    return {"files": len(files), "size_kb": round(sum(p.stat().st_size for p in files) / 1024),
            "last_backup": last_backup, "disk": disk}


def snapshot(now=None):
    now = time.time() if now is None else float(now)
    from backend import alerts, sensors, live_track, vision
    from backend.app.auth import store, tokens

    try:
        sensor = sensors.status()
        sensor_view = {k: sensor.get(k) for k in
                       ("configured", "samples", "total_samples", "uptime_pct", "stale_s",
                        "last_error", "poll_s", "note")}
    except Exception as e:  # noqa: BLE001
        sensor_view = {"configured": False, "error": type(e).__name__}
    try:
        live = live_track.status(now=now)
    except Exception:
        live = {"active_sessions": 0, "warm": False, "last_activity_age_s": None}
    try:
        v = vision.status()
        engine = "api" if (v.get("groq_configured") or v.get("gemini_configured")) else "yolo"
    except Exception:
        engine = "unknown"
    live["engine"] = engine
    try:
        conf = alerts.config_summary()
        sms = {"textbee_configured": conf.get("textbee_configured"),
               "providers_configured": conf.get("providers_configured", {}),
               "providers": conf.get("providers", []),
               "phones_configured": conf.get("phones_configured", 0),
               "smsgate": _smsgate_reachable()}
    except Exception:
        sms = {"textbee_configured": False, "providers_configured": {}}
    try:
        users = len(store.list_users())
        sessions_n = tokens.active_count(now)
    except Exception:
        users, sessions_n = 0, 0
    return {
        "generated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "farm_time": farm_clock.farm_now(now).isoformat(),
        "farm_tz": os.environ.get("AQUA_FARM_TZ", "Asia/Kolkata"),
        "uptime_s": round(max(0.0, now - _START)),
        "sensors": sensor_view,
        "sms": sms,
        "live": live,
        "auth": {"mode": os.environ.get("AQUA_AUTH_MODE", "full"),
                 "users": users, "sessions_active": sessions_n},
        "data": _data_stats(),
        "flags": _effective_flags(),
        "note": "Read-only diagnostics; secrets, phones and raw media are never included.",
    }

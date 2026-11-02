"""Feeding log, post-feed response grading, and DO feed-dip evidence (Track IV F1).

A feeding event is logged by the farmer's one tap. Ten minutes later the
camera-window pipeline supplies a PROVISIONAL appetite grade by comparing
mean track speed before and after the feed. Two consecutive weak/none grades
raise one English SMS through the existing alert chain (R9).

No feeder is controlled. No new poller is created.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.app.services import behaviour_service, farm_clock

MAX_FILE_BYTES = 50 * 1024 * 1024
PRE_WINDOW_S = 30 * 60
POST_WINDOW_S = 10 * 60
DIP_START_H = 2.0
DIP_END_H = 4.0
S_FEED = -0.08
GRADES = ("aggressive", "moderate", "weak", "none")
WEAK_MESSAGE = ("AquaAI FEED ALERT: Weak feeding response 2 times in a row. "
                "Check water/DO/fish health! -AquaAI")
MODEL_VERSION = "feed-v1"

_lock = threading.RLock()


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[2] / "data"))


def _file():
    return _data_dir() / "feeding_log.jsonl"


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def enabled():
    return _env_flag("AQUA_FEED_LOG", True)


def alert_enabled():
    return _env_flag("AQUA_FEED_ALERT", True)


def dip_enabled():
    return _env_flag("AQUA_DO_FEED_DIP", True)


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _iso(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()


def _epoch(raw):
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _rotate(p):
    try:
        if p.is_file() and p.stat().st_size > MAX_FILE_BYTES:
            p.replace(p.with_suffix(p.suffix + ".1"))
    except OSError:
        pass


def read_events(days=30):
    cutoff = farm_clock.farm_now().timestamp() - days * 86400
    rows = []
    try:
        p = _file()
        if not p.is_file():
            return rows
        for line in p.read_text(encoding="utf-8").splitlines()[-20000:]:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and (r.get("fed_t") or 0) >= cutoff:
                rows.append(r)
    except OSError:
        pass
    rows.sort(key=lambda r: r.get("fed_t") or 0)
    return rows


def _write_all(rows):
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".jsonl.tmp")
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    tmp.write_text(text + ("\n" if text else ""), encoding="utf-8")
    tmp.replace(p)


def _append(rec):
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    _rotate(p)
    with _lock:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def log_feeding(fed_at=None, note=None):
    if not enabled():
        raise PermissionError("Feeding log is disabled (AQUA_FEED_LOG=0)")
    fed_at = time.time() if fed_at is None else float(fed_at)
    rec = {
        "id": uuid.uuid4().hex,
        "fed_at": _iso(fed_at),
        "fed_t": fed_at,
        "farm_day": farm_clock.farm_day(fed_at),
        "note": str(note or "").strip()[:160] or None,
        "response": None,
        "response_delta": None,
        "response_updated_at": None,
        "source": "farmer-tap",
        "provisional": True,
        "model_version": MODEL_VERSION,
    }
    with _lock:
        _append(rec)
    return rec


def _grade_feed(row, observations, now):
    fed_t = float(row["fed_t"])
    if now < fed_t + POST_WINDOW_S:
        return None, None
    pre, post = [], []
    post_rows = 0
    post_tracks = 0
    for o in observations:
        t = float(o.get("window_end_t") or 0)
        value = _num((o.get("metrics") or {}).get("speed_mean_pxs"))
        if fed_t - PRE_WINDOW_S <= t < fed_t and value is not None:
            pre.append(value)
        elif fed_t <= t <= fed_t + POST_WINDOW_S:
            post_rows += 1
            post_tracks += int((o.get("metrics") or {}).get("count_confirmed") or 0)
            if value is not None:
                post.append(value)
    if not pre:
        return None, None
    if post_rows and post_tracks == 0:
        return "none", -1.0
    if not post:
        return None, None
    pre_mean = sum(pre) / len(pre)
    post_mean = sum(post) / len(post)
    if pre_mean <= 1e-9:
        return None, None
    delta = (post_mean - pre_mean) / pre_mean
    if delta >= 0.30:
        grade = "aggressive"
    elif delta >= 0.10:
        grade = "moderate"
    elif delta >= 0.0:
        grade = "weak"
    else:
        grade = "none"
    return grade, round(delta, 4)


def update_responses(now=None):
    """Grade any feeding that has a complete +10 min window. Returns updated rows."""
    now = time.time() if now is None else float(now)
    if not enabled():
        return []
    observations = behaviour_service.read_observations(2)
    updated = []
    with _lock:
        rows = read_events(30)
        dirty = False
        for row in rows:
            if row.get("response") is not None:
                continue
            grade, delta = _grade_feed(row, observations, now)
            if grade is None:
                continue
            row["response"] = grade
            row["response_delta"] = delta
            row["response_updated_at"] = _iso(now)
            updated.append(row)
            dirty = True
        if dirty:
            _write_all(rows)
    if updated:
        _maybe_weak_alert(rows, now)
    return updated


def _maybe_weak_alert(rows, now):
    if not alert_enabled() or len(rows) < 2:
        return False
    last_two = rows[-2:]
    if any(r.get("response") not in ("weak", "none") for r in last_two):
        return False
    try:
        from backend import alerts
        return bool(alerts.send_alert("R9", WEAK_MESSAGE, "HIGH", now=now, sms=True))
    except Exception:
        return False


def feed_effect(now=None):
    """Latest feeding's DO penalty only during the +2..+4 h digestion window."""
    now = time.time() if now is None else float(now)
    rows = read_events(2)
    if not rows:
        return {"last_feed_age_h": None, "s_feed": 0.0,
                "window_hours": [DIP_START_H, DIP_END_H], "advisory": None}
    last = rows[-1]
    age_h = max(0.0, (now - float(last.get("fed_t") or now)) / 3600.0)
    active = dip_enabled() and DIP_START_H <= age_h <= DIP_END_H
    return {"last_feed_age_h": round(age_h, 2),
            "s_feed": S_FEED if active else 0.0,
            "window_hours": [DIP_START_H, DIP_END_H],
            "advisory": None}


def counts_today(now=None):
    now = time.time() if now is None else float(now)
    day = farm_clock.farm_day(now)
    return sum(1 for r in read_events(2) if r.get("farm_day") == day)


def latest(now=None):
    now = time.time() if now is None else float(now)
    rows = [r for r in read_events(30) if float(r.get("fed_t") or 0) <= now]
    return rows[-1] if rows else None

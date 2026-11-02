"""Dissolved-oxygen prediction service (Track II D1).

Gathers the latest live temperature/turbidity from the read-only sensor
mirror, the latest manual pH reading, and the dormant kit-calibration file,
then calls the pure model in do_model.py.

No hardware is controlled. No new poller/thread is created.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from backend import sensors, water
from backend.app.services import do_model, farm_clock, feeding_service

MAX_FILE_BYTES = 50 * 1024 * 1024
MIN_CAL_READINGS = 20
REFIT_EVERY = 10
_lock = threading.RLock()


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[2] / "data"))


def _readings_file():
    return _data_dir() / "do_readings.jsonl"


def _cal_file():
    return _data_dir() / "do_cal.json"


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _env_float(name, default):
    try:
        v = float(os.environ.get(name, ""))
        return v if math.isfinite(v) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _now(now=None):
    return time.time() if now is None else float(now)


def _rotate(p, max_bytes=MAX_FILE_BYTES):
    try:
        if p.is_file() and p.stat().st_size > max_bytes:
            p.replace(p.with_suffix(p.suffix + ".1"))
    except OSError:
        pass


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _latest_point(field, now):
    rows = []
    for t, v in sensors.series(field, 7 * 1440):
        value = _num(v)
        if t <= now + 300 and value is not None:
            rows.append((float(t), value))
    if not rows:
        return None, None
    t, v = rows[-1]
    return v, max(0.0, now - t)


def _latest_ph(now):
    records, _ = water.read_all()
    gone = {r.get("supersedes") for r in records if r.get("supersedes")}
    rows = []
    for r in records:
        if r.get("id") in gone:
            continue
        m = (r.get("measurements") or {}).get("pH")
        if not isinstance(m, dict):
            continue
        value = _num(m.get("canonicalValue"))
        if value is None:
            continue
        try:
            ts = datetime.fromisoformat(str(r.get("timestamp")).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
        rows.append((ts, value))
    if not rows:
        return None, None
    ts, value = max(rows, key=lambda x: x[0])
    return value, max(0.0, (now - ts) / 3600.0)


def _dt_2h(now):
    rows = []
    for t, v in sensors.series("temperature", 240):
        value = _num(v)
        if t <= now + 300 and value is not None:
            rows.append((float(t), value))
    if len(rows) < 2:
        return 0.0
    target = now - 2 * 3600
    ref = min(rows, key=lambda x: abs(x[0] - target))
    if abs(ref[0] - target) > 1800:
        return 0.0
    return rows[-1][1] - ref[1]


def _stale_s():
    return _env_float("AQUA_DO_STALE_MIN", 20.0) * 60.0


def _age_label(age_s):
    if age_s >= 7200:
        return f"{age_s / 3600.0:.0f} h"
    return f"{age_s / 60.0:.0f} min"


def _inputs(temp, temp_age, ntu, ntu_age, ph, ph_age_h):
    return {
        "temp_c": round(temp, 2) if temp is not None else None,
        "temp_age_min": int(round(temp_age / 60.0)) if temp_age is not None else None,
        "turbidity_ntu": round(ntu, 1) if ntu is not None else None,
        "turbidity_age_min": int(round(ntu_age / 60.0)) if ntu_age is not None else None,
        "ph": round(ph, 2) if ph is not None else None,
        "ph_age_hours": round(ph_age_h, 1) if ph_age_h is not None else None,
    }


def _base(now):
    return {
        "status": "ok",
        "do_mgl": None,
        "band_low": None,
        "band_high": None,
        "percent_saturation": None,
        "do_sat_mgl": None,
        "s_factor": None,
        "risk_level": None,
        "confidence": "low",
        "label_provisional": True,
        "inputs": _inputs(None, None, None, None, None, None),
        "turbidity_unit": "raw_adc",
        "behaviour_evidence": None,
        "feed_evidence": None,
        "reason": None,
        "generated_at": _iso(now),
        "model_version": do_model.MODEL_VERSION,
    }


def prediction(now=None):
    now = _now(now)
    out = _base(now)
    if not _env_flag("AQUA_DO_PREDICT", True):
        out["status"] = "disabled"
        out["reason"] = "DO prediction disabled (AQUA_DO_PREDICT=0)"
        return out

    temp, temp_age = _latest_point("temperature", now)
    ntu, ntu_age = _latest_point("turbidity", now)
    ph, ph_age_h = _latest_ph(now)
    out["inputs"] = _inputs(temp, temp_age, ntu, ntu_age, ph, ph_age_h)

    problems = []
    stale = _stale_s()
    if temp is None:
        problems.append("temperature missing")
    elif temp_age is not None and temp_age > stale:
        problems.append(f"temp {_age_label(temp_age)} old")
    if ntu is None:
        problems.append("turbidity missing")
    elif ntu_age is not None and ntu_age > stale:
        problems.append(f"turbidity {_age_label(ntu_age)} old")
    if problems:
        out["status"] = "insufficient_data"
        out["reason"] = "sensors unusable: " + "; ".join(problems)
        return out

    ph_used = ph if ph is not None and ph_age_h is not None and ph_age_h <= 24.0 else None
    feed_ev = feeding_service.feed_effect(now)
    out["feed_evidence"] = feed_ev
    try:
        est = do_model.estimate_do(
            temp=temp,
            ntu=ntu,
            ph=ph_used,
            hour=farm_clock.farm_hour(now),
            dT_2h=_dt_2h(now),
            s_feed=feed_ev.get("s_feed") or 0.0,
            cal=_active_calibration(),
        )
    except Exception as e:  # noqa: BLE001 - an estimate must never break the API
        out["status"] = "insufficient_data"
        out["reason"] = f"estimate failed: {type(e).__name__}"
        return out

    for key in ("do_mgl", "band_low", "band_high", "percent_saturation",
                "do_sat_mgl", "s_factor", "risk_level"):
        out[key] = est.get(key)
    out["confidence"] = est.get("confidence", "low")
    out["label_provisional"] = est.get("label_provisional", True)
    # BEH-B wiring point: behaviour can escalate the risk band, never the mg/L number.
    try:
        from backend.app.services import behaviour_service
        evidence = behaviour_service.evidence(now=now)
        out["behaviour_evidence"] = evidence
        if evidence and _env_flag("AQUA_BEH_DO_LINK", True):
            level, _note = behaviour_service.escalate_with_behaviour(out.get("risk_level"),
                                                                    evidence.get("state"))
            out["risk_level"] = level
    except Exception:
        out["behaviour_evidence"] = None
    age_h = (out.get("feed_evidence") or {}).get("last_feed_age_h")
    if out.get("risk_level") in ("risk", "critical") and age_h is not None and age_h <= 4.0:
        out["feed_evidence"] = {**out["feed_evidence"],
                                "advisory": "Estimated DO is low; delay the next feeding or feed less."}
    return out


def read_readings():
    rows = []
    try:
        p = _readings_file()
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    if isinstance(r, dict):
                        rows.append(r)
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def append_reading(rec):
    p = _readings_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    _rotate(p)
    with _lock:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def recent_readings(limit=50):
    rows = read_readings()
    rows.sort(key=lambda r: r.get("measured_t") or 0, reverse=True)
    return rows[:max(1, min(int(limit), 200))]


def _pairs(rows=None):
    out = []
    for r in (read_readings() if rows is None else rows):
        x = _num(r.get("do_est"))
        y = _num(r.get("value_mgl"))
        if x is not None and y is not None:
            out.append((x, y))
    return out


def fit_calibration(rows=None):
    pairs = _pairs(rows)
    if len(pairs) < MIN_CAL_READINGS:
        return None
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    var = sum((x - mx) ** 2 for x, _ in pairs)
    if var <= 1e-12:
        a, b = 0.0, my
    else:
        cov = sum((x - mx) * (y - my) for x, y in pairs)
        a = cov / var
        b = my - a * mx
    cal = {"a": round(a, 6), "b": round(b, 6), "n": len(pairs), "fitted_at": _iso(time.time())}
    try:
        p = _cal_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cal), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass
    return cal


def read_calibration():
    try:
        p = _cal_file()
        if not p.is_file():
            return None
        cal = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(cal, dict):
            return None
        a, b = _num(cal.get("a")), _num(cal.get("b"))
        n = int(cal.get("n") or 0)
        if a is None or b is None or n < MIN_CAL_READINGS:
            return None
        return {**cal, "a": a, "b": b, "n": n}
    except (OSError, ValueError):
        return None


def _active_calibration():
    if not _env_flag("AQUA_DO_CAL", False):
        return None
    cal = read_calibration()
    n = len(_pairs())
    if n < MIN_CAL_READINGS:
        return None
    if cal is None or n >= cal["n"] + REFIT_EVERY:
        cal = fit_calibration()
    return cal if cal and cal.get("n", 0) >= MIN_CAL_READINGS else None


def maybe_fit():
    """Fit after a new reading when the dormant calibration flag is enabled."""
    if not _env_flag("AQUA_DO_CAL", False):
        return None
    cal = read_calibration()
    n = len(_pairs())
    if n >= MIN_CAL_READINGS and (cal is None or n >= cal["n"] + REFIT_EVERY):
        return fit_calibration()
    return cal

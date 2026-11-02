"""Fish-behaviour metrics + Hypoxia Behaviour Score (BEH-A) and DO link (BEH-B).

All inputs are confirmed camera tracks aggregated client-side into 5-minute
windows. This module is advisory only: no hardware control, no diagnosis.
The score is a PROVISIONAL proxy, not a probability and not a mg/L number.

Constants are grouped here with the R-numbers from the BEH spec.
"""
from __future__ import annotations

import json
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.app.services import farm_clock

MAX_FILE_BYTES = 50 * 1024 * 1024
WINDOW_S = 300
SUSTAIN_WINDOWS = 3                 # R-B2: tilapia gasping >= 15 min
DEESCALATE_CALM_WINDOWS = 2
SIDE_SURFACE_FULL = 0.30            # HBS side-view surface_ratio full scale
TOP_EDGE_FULL = 0.50                # HBS top-view edge_ratio full scale
LETHARGY_FULL = 0.50
SPEED_Z_FULL = 2.0
ERRATIC_Z_FULL = 3.0
RESTLESS_HBS = 30.0
MODEL_VERSION = "beh-hbs-v1"
DEFAULT_HBS_SUSPECT = 60.0
DEFAULT_WARMUP_DAYS = 3
BASELINE_METRICS = ("surface_ratio", "vertical_cg", "edge_ratio",
                    "spread_index", "speed_mean_pxs", "lethargy_ratio")

_lock = threading.RLock()


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[2] / "data"))


def _obs_file():
    return _data_dir() / "behaviour_obs.jsonl"


def _baseline_file():
    return _data_dir() / "behaviour_baseline.json"


def _env_float(name, default):
    try:
        v = float(os.environ.get(name, ""))
        return v if math.isfinite(v) else float(default)
    except (TypeError, ValueError):
        return float(default)


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


def _num(v, default=None):
    if isinstance(v, bool):
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


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


def threshold():
    return _env_float("AQUA_BEH_HBS_SUSPECT", DEFAULT_HBS_SUSPECT)


def warmup_days():
    return max(0, _env_int("AQUA_BEH_WARMUP_DAYS", DEFAULT_WARMUP_DAYS))


def alert_enabled():
    return _env_flag("AQUA_BEH_ALERT", True)


def read_observations(days=7):
    rows = []
    cutoff = farm_clock.farm_now().timestamp() - days * 86400
    try:
        p = _obs_file()
        if not p.is_file():
            return rows
        for line in p.read_text(encoding="utf-8").splitlines()[-20000:]:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            t = _num(r.get("window_end_t"))
            if t is None or t < cutoff:
                continue
            rows.append(r)
    except OSError:
        pass
    rows.sort(key=lambda r: r.get("window_end_t") or 0)
    return rows


def append_observation(rec):
    p = _obs_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    _rotate(p)
    with _lock:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load_baseline():
    try:
        p = _baseline_file()
        if not p.is_file():
            return {"metrics": {}, "updated_at": None}
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) and isinstance(raw.get("metrics"), dict) else {"metrics": {}}
    except (OSError, ValueError):
        return {"metrics": {}}


def _save_baseline(data):
    try:
        p = _baseline_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def update_baseline(rec):
    """Welford update per metric per farm-local hour (R-B1 baselines)."""
    hour = str(farm_clock.farm_now(rec["window_end_t"]).hour)
    metrics = rec.get("metrics") or {}
    data = _load_baseline()
    for name in BASELINE_METRICS:
        value = _num(metrics.get(name))
        if value is None:
            continue
        cell = data["metrics"].setdefault(name, {}).setdefault(hour, {"n": 0, "mean": 0.0, "m2": 0.0})
        n = int(cell.get("n") or 0) + 1
        delta = value - float(cell.get("mean") or 0.0)
        mean = float(cell.get("mean") or 0.0) + delta / n
        m2 = float(cell.get("m2") or 0.0) + delta * (value - mean)
        cell.update(n=n, mean=mean, m2=m2)
    data["updated_at"] = _iso(rec["window_end_t"])
    _save_baseline(data)


def _z(metric, value, hour, baseline):
    cell = (baseline.get("metrics") or {}).get(metric, {}).get(str(hour))
    if not cell or int(cell.get("n") or 0) < 2:
        return None
    n = int(cell["n"])
    std = math.sqrt(max(0.0, float(cell.get("m2") or 0.0)) / (n - 1))
    if std <= 1e-9:
        return None
    return (float(value) - float(cell.get("mean") or 0.0)) / std


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def hbs_for(metrics, view, speed_z=None, erratic_z=None):
    """Deterministic HBS v1; returns 0-100, or None for missing metrics."""
    m = metrics or {}
    if view == "top":
        base = _num(m.get("edge_ratio"))
        term = 0.0 if base is None else _clamp(base / TOP_EDGE_FULL, 0.0, 1.0)
    else:
        base = _num(m.get("surface_ratio"))
        term = 0.0 if base is None else _clamp(base / SIDE_SURFACE_FULL, 0.0, 1.0)
    lethargy = _num(m.get("lethargy_ratio"))
    if lethargy is None:
        return None
    sz = _num(speed_z, 0.0)
    ez = _num(erratic_z, 0.0)
    raw = (40.0 * term
           + 25.0 * _clamp(lethargy / LETHARGY_FULL, 0.0, 1.0)
           + 20.0 * _clamp(-sz / SPEED_Z_FULL, 0.0, 1.0)
           + 15.0 * _clamp(ez / ERRATIC_Z_FULL, 0.0, 1.0))
    return int(round(_clamp(raw, 0.0, 100.0)))


def _validate_metrics(raw, view):
    if not isinstance(raw, dict):
        return None, "metrics must be an object"
    out = {}
    common = {
        "speed_mean_pxs": (0.0, None), "lethargy_ratio": (0.0, 1.0),
        "speed_z": (None, None), "erratic_z": (None, None),
        "count_confirmed": (0, None),
        "surface_ratio": (0.0, 1.0), "vertical_cg": (0.0, 1.0),
        "edge_ratio": (0.0, 1.0), "spread_index": (0.0, 1.0),
    }
    required = {"count_confirmed", "lethargy_ratio"}
    required.update({"surface_ratio", "vertical_cg"} if view == "side" else {"edge_ratio"})
    for name, (lo, hi) in common.items():
        if name not in raw:
            if name in required:
                return None, f"metrics.{name} is required"
            continue
        v = _num(raw.get(name))
        if v is None:
            return None, f"metrics.{name} must be a finite number"
        if lo is not None and v < lo:
            return None, f"metrics.{name} must be >= {lo}"
        if hi is not None and v > hi:
            return None, f"metrics.{name} must be <= {hi}"
        if name == "count_confirmed" and v != int(v):
            return None, "metrics.count_confirmed must be an integer"
        out[name] = int(v) if name == "count_confirmed" else v
    if out["count_confirmed"] < 0:
        return None, "metrics.count_confirmed must be >= 0"
    return out, None


def _view_term_value(metrics, view):
    return metrics.get("edge_ratio") if view == "top" else metrics.get("surface_ratio")


def _hbs_row(row, baseline=None):
    metrics = row.get("metrics") or {}
    view = row.get("view") or "side"
    hour = farm_clock.farm_now(row.get("window_end_t") or 0).hour
    sz = _z("speed_mean_pxs", metrics.get("speed_mean_pxs"), hour, baseline) if baseline else None
    if sz is None:
        sz = metrics.get("speed_z", 0.0)
    return hbs_for(metrics, view, speed_z=sz, erratic_z=metrics.get("erratic_z", 0.0))


def _contiguous_tail(rows):
    if not rows:
        return []
    tail = [rows[-1]]
    for r in reversed(rows[:-1]):
        if (tail[0].get("window_end_t") or 0) - (r.get("window_end_t") or 0) > WINDOW_S + 60:
            break
        tail.insert(0, r)
    return tail


def summary(now=None):
    now = farm_clock.farm_now().timestamp() if now is None else float(now)
    rows = read_observations(7)
    days_seen = len({farm_clock.farm_day(r.get("window_end_t") or 0) for r in rows})
    required = warmup_days()
    base = {
        "state": "no_data",
        "hbs": None,
        "sustained_min": 0,
        "view": None,
        "window_start": None,
        "window_end": None,
        "metrics": {},
        "z_scores": {},
        "baseline": {"days": days_seen, "required": required,
                     "windows": len(rows), "ok": days_seen >= required},
        "threshold": threshold(),
        "label_provisional": True,
        "model_version": MODEL_VERSION,
        "reason": "no behaviour observations",
        "generated_at": _iso(now),
    }
    if not rows:
        return base

    latest = rows[-1]
    base["view"] = latest.get("view")
    base["window_start"] = latest.get("window_start")
    base["window_end"] = latest.get("window_end")
    base["reason"] = None

    last3 = rows[-3:]
    no_tracks = len(last3) >= 3 and all(int(r.get("metrics", {}).get("count_confirmed") or 0) == 0 for r in last3)
    stale = now - float(latest.get("window_end_t") or 0) > SUSTAIN_WINDOWS * WINDOW_S
    if no_tracks or stale:
        base["state"] = "no_data"
        base["reason"] = "camera off / no confirmed tracks for 15 min" if no_tracks else "no behaviour window for 15 min"
        return base

    baseline = _load_baseline()
    tail = _contiguous_tail(rows)[-4:]
    hbs_rows = [(_hbs_row(r, baseline), r) for r in tail]
    latest_hbs = hbs_rows[-1][0]
    base["metrics"] = {**(latest.get("metrics") or {}), "hbs": latest_hbs}
    latest_hour = farm_clock.farm_now(latest.get("window_end_t") or 0).hour
    zs = {}
    for name in BASELINE_METRICS:
        v = (latest.get("metrics") or {}).get(name)
        z = _z(name, v, latest_hour, baseline) if v is not None else None
        if z is not None:
            zs[name] = round(z, 2)
    payload_sz = (latest.get("metrics") or {}).get("speed_z")
    payload_ez = (latest.get("metrics") or {}).get("erratic_z")
    if "speed_mean_pxs" not in zs and payload_sz is not None:
        zs["speed_z"] = round(float(payload_sz), 2)
    if payload_ez is not None:
        zs["erratic_z"] = round(float(payload_ez), 2)
    base["z_scores"] = zs

    if days_seen < required:
        base["state"] = "warming_up"
        base["reason"] = f"baseline building (day {days_seen}/{required})"
        return base
    if latest_hbs is None:
        base["state"] = "warming_up"
        base["reason"] = "not enough metric history"
        return base

    base["hbs"] = latest_hbs
    th = threshold()
    values = [h for h, _ in hbs_rows]
    suspect = False
    if len(values) >= SUSTAIN_WINDOWS and all(v is not None and v >= th for v in values[-SUSTAIN_WINDOWS:]):
        suspect = True
    elif len(values) >= 4 and sum(1 for v in values if v is not None and v >= th) >= 3:
        if not all(v is not None and v < th for v in values[-DEESCALATE_CALM_WINDOWS:]):
            suspect = True

    if suspect:
        consecutive = 0
        for v in reversed(values):
            if v is not None and v >= th:
                consecutive += 1
            else:
                break
        base["state"] = "hypoxia_suspect"
        base["sustained_min"] = max(SUSTAIN_WINDOWS * (WINDOW_S // 60), consecutive * (WINDOW_S // 60))
    elif latest_hbs >= (th / 2.0):
        base["state"] = "restless"
        base["sustained_min"] = 0
    else:
        base["state"] = "calm"
        base["sustained_min"] = 0
    return base


def evidence(now=None):
    """BEH-B camera evidence; null unless the sustained suspect state is active."""
    s = summary(now=now)
    if s.get("state") != "hypoxia_suspect":
        return None
    return {"hbs": s.get("hbs"), "state": s.get("state"),
            "sustained_min": s.get("sustained_min"), "source": "camera-tracks"}


def escalate_with_behaviour(risk_level, behaviour_state):
    """Pure escalation: never changes the numeric DO estimate."""
    levels = ("safe", "watch", "risk", "critical")
    if behaviour_state != "hypoxia_suspect" or risk_level not in levels:
        return risk_level, None
    idx = min(len(levels) - 1, levels.index(risk_level) + 1)
    if idx == levels.index(risk_level):
        return risk_level, "behaviour already compatible with critical risk"
    return levels[idx], "camera behaviour: gasping/lethargy suspected"


def behaviour_message(sustained_min):
    return (f"AquaAI BEHAVIOUR: Fish at surface/lethargic for {int(sustained_min)} min "
            "- low DO likely! Check aeration, change water. -AquaAI")


def _maybe_immediate_sms(prev_state, new_summary, now):
    if not alert_enabled() or new_summary.get("state") != "hypoxia_suspect":
        return False
    if prev_state == "hypoxia_suspect":
        return False
    try:
        from backend import alerts
        alerts.send_alert("R8", behaviour_message(new_summary.get("sustained_min") or 15),
                          "CRITICAL", now=now, sms=True)
        # R8 is an emergency with no cooldown gate. Mark it active so the
        # alert engine's evaluate() loop does not fire it a second time on
        # the same transition; a fresh transition (or restart) fires again.
        alerts._prev_active.add("R8")
        return True
    except Exception:
        return False


def record_observation(payload):
    """Validate, persist, update baseline, and return (rec, summary, sms_sent)."""
    if not isinstance(payload, dict):
        raise ValueError("Send a JSON object.")
    start = _epoch(payload.get("window_start"))
    end = _epoch(payload.get("window_end"))
    if start is None or end is None:
        raise ValueError("window_start and window_end are required ISO date-times.")
    if end <= start:
        raise ValueError("window_end must be after window_start.")
    if not (60 <= end - start <= 600):
        raise ValueError("window must be between 1 and 10 minutes.")
    view = payload.get("view")
    if view not in ("side", "top"):
        raise ValueError("view must be 'side' or 'top'.")
    metrics, err = _validate_metrics(payload.get("metrics") if "metrics" in payload else payload, view)
    if err:
        raise ValueError(err)
    rec = {
        "id": uuid.uuid4().hex,
        "window_start": _iso(start),
        "window_end": _iso(end),
        "window_start_t": start,
        "window_end_t": end,
        "view": view,
        "metrics": metrics,
        "source": "camera-tracks",
        "created_at": _iso(farm_clock.farm_now().timestamp()),
        "provisional": True,
        "model_version": MODEL_VERSION,
    }
    prev_state = summary(now=end).get("state")
    append_observation(rec)
    update_baseline(rec)
    new_summary = summary(now=end)
    sms = _maybe_immediate_sms(prev_state, new_summary, end)
    return rec, new_summary, sms

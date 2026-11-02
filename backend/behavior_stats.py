"""EXPERIMENTAL camera-behaviour windows (farmer finalization, D).

Confirmed live tracks are folded into 5-minute windows:
- activity: mean track speed (px/s) normalised by the frame diagonal;
- schooling/spread: mean pairwise centroid distance / diagonal;
- surface proxy: fraction of track observations in the top 15% of the frame.

A 7-day, hour-of-day median/MAD baseline flags sustained deviation (|z|>3 for
3 consecutive windows, i.e. 15 minutes) which feeds rule R6. IMPORTANT: these
are top-view camera proxies, not a diagnosis. Without a DO sensor they cannot
be calibrated against oxygen events; the UI says so. Surface proximity is only
a proxy for gasping (a real judgement needs a human eye).

Storage: backend/data/behavior_windows.jsonl, rotated at 50 MB.
"""
import json
import math
import os
import threading
import time
from datetime import datetime
from pathlib import Path

MAX_FILE_BYTES = 50 * 1024 * 1024
WINDOW_S = 300
SURFACE_BAND = 0.15
BASELINE_DAYS = 7
SUSTAIN_WINDOWS = 3
METRICS = ("activity_norm", "spread_norm", "surface_occ")

_lock = threading.RLock()
_windows = {}
_last_minute = 0


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[1] / "backend" / "data"))


def _file():
    return _data_dir() / "behavior_windows.jsonl"


def _rotate(p, max_bytes=MAX_FILE_BYTES):
    try:
        if p.is_file() and p.stat().st_size > max_bytes:
            p.replace(p.with_suffix(p.suffix + ".1"))
    except OSError:
        pass


def _median(vals):
    s = sorted(vals)
    n = len(s)
    return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2) if s else None


def _mad(vals, med=None):
    med = _median(vals) if med is None else med
    return _median([abs(v - med) for v in vals]) if vals and med is not None else 0.0


def _center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _flush(key, w):
    rec = {"window_start": key, "t": key,
           "iso": datetime.fromtimestamp(key).isoformat(),
           "n_frames": w["frames"],
           "n_obs": w["obs"],
           "activity_px_s": round(sum(w["px_speeds"]) / len(w["px_speeds"]), 2) if w["px_speeds"] else None,
           "activity_norm": round(sum(w["activity"]) / len(w["activity"]), 6) if w["activity"] else None,
           "spread_norm": round(sum(w["spread"]) / len(w["spread"]), 6) if w["spread"] else None,
           "surface_occ": round(w["surface"] / w["obs"], 4) if w["obs"] else None,
           "provisional": True,
           "experimental": True}
    try:
        p = _file()
        p.parent.mkdir(parents=True, exist_ok=True)
        _rotate(p)
        with _lock:
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return rec


def observe(tracks, width, height, now=None):
    """Fold one analysed frame's confirmed tracks into the current window."""
    now = time.time() if now is None else float(now)
    key = int(now // WINDOW_S) * WINDOW_S
    diag = math.hypot(max(1, width), max(1, height))
    good = [t for t in (tracks or []) if t.get("confirmed") is not False
            and t.get("static") is not True and t.get("box")]
    with _lock:
        for k in [k for k in _windows if k < key]:
            _flush(k, _windows.pop(k))
        w = _windows.setdefault(key, {"frames": 0, "obs": 0, "activity": [], "spread": [],
                                      "surface": 0, "px_speeds": []})
        w["frames"] += 1
        if not good:
            return
        w["obs"] += len(good)
        centers = []
        for t in good:
            box = t["box"]
            centers.append(_center(box))
            sp = t.get("mean_speed_px_sec")
            if isinstance(sp, (int, float)):
                w["activity"].append(float(sp) / diag)
                w["px_speeds"].append(float(sp))
            elif len(t.get("speeds") or []) == 0:
                pass
            if _center(box)[1] < SURFACE_BAND:
                w["surface"] += 1
        if len(centers) >= 2:
            dists = []
            for i in range(len(centers)):
                for j in range(i + 1, len(centers)):
                    dists.append(math.hypot(centers[i][0] - centers[j][0], centers[i][1] - centers[j][1]) / diag)
            w["spread"].append(sum(dists) / len(dists))


def _load_windows(days=BASELINE_DAYS):
    out = []
    try:
        p = _file()
        if not p.is_file():
            return out
        cutoff = time.time() - days * 86400
        for line in p.read_text(encoding="utf-8").splitlines()[-20000:]:
            try:
                r = json.loads(line)
                if isinstance(r.get("window_start"), (int, float)) and r["window_start"] >= cutoff:
                    out.append(r)
            except ValueError:
                continue
    except OSError:
        pass
    return out


def baseline():
    rows = _load_windows()
    by_hour = {}
    days = set()
    for r in rows:
        hour = datetime.fromtimestamp(r["window_start"]).hour
        days.add(datetime.fromtimestamp(r["window_start"]).date())
        for m in METRICS:
            v = r.get(m)
            if isinstance(v, (int, float)):
                by_hour.setdefault((hour, m), []).append(float(v))
    door = {}
    for (hour, m), vals in by_hour.items():
        if len(vals) >= 12:
            med = _median(vals)
            door[(hour, m)] = {"median": round(med, 6), "mad": round(_mad(vals, med), 6), "n": len(vals)}
    return {"windows": len(rows), "days": len(days), "hours_covered": len({h for h, _ in door}),
            "by_hour": door, "provisional": True,
            "note": ("Baseline uses available history only; owner verification of a full 7-day "
                     "baseline is still required.")}


def _z(metric, value, hour, base):
    b = base["by_hour"].get((hour, metric))
    if not b or b["mad"] <= 1e-9 or not isinstance(value, (int, float)):
        return None
    return 0.6745 * (value - b["median"]) / b["mad"]


def current_anomaly(now=None):
    """Sustained (3 consecutive windows, same metric) |z|>3 deviation."""
    now = time.time() if now is None else float(now)
    with _lock:
        for k in list(_windows):
            if now - k >= WINDOW_S:
                _flush(k, _windows.pop(k))
    rows = _load_windows()
    rows.sort(key=lambda r: r["window_start"])
    last = rows[-SUSTAIN_WINDOWS:]
    if len(last) < SUSTAIN_WINDOWS:
        return None
    base = baseline()
    per_metric = {}
    for m in METRICS:
        zs = []
        for r in last:
            hour = datetime.fromtimestamp(r["window_start"]).hour
            z = _z(m, r.get(m), hour, base)
            if z is None:
                zs = []
                break
            zs.append(z)
        if len(zs) == SUSTAIN_WINDOWS and all(abs(z) > 3 for z in zs):
            per_metric[m] = zs[-1]
    if not per_metric:
        return None
    metric, z = max(per_metric.items(), key=lambda kv: abs(kv[1]))
    return {"metric": metric, "z": round(z, 2), "sustained": True,
            "windows": SUSTAIN_WINDOWS, "window_min": WINDOW_S // 60,
            "baseline_days": base["days"], "provisional": True}


def summary(now=None):
    now = time.time() if now is None else float(now)
    with _lock:
        for k in list(_windows):
            if now - k >= WINDOW_S:
                _flush(k, _windows.pop(k))
    rows = [r for r in _load_windows(1) if r["window_start"] >= now - 86400]
    latest = rows[-1] if rows else None
    series = [{"t": r["window_start"], "activity": r.get("activity_norm"),
               "spread": r.get("spread_norm"), "surface": r.get("surface_occ")} for r in rows]
    with _lock:
        if not latest and _windows:
            w_key = max(_windows.keys())
            w = _windows[w_key]
            if w.get("obs", 0) > 0:
                latest = {
                    "window_start": w_key,
                    "t": w_key,
                    "iso": datetime.fromtimestamp(w_key).isoformat(),
                    "n_frames": w["frames"],
                    "n_obs": w["obs"],
                    "activity_px_s": round(sum(w["px_speeds"]) / len(w["px_speeds"]), 2) if w["px_speeds"] else None,
                    "activity_norm": round(sum(w["activity"]) / len(w["activity"]), 6) if w["activity"] else None,
                    "spread_norm": round(sum(w["spread"]) / len(w["spread"]), 6) if w["spread"] else None,
                    "surface_occ": round(w["surface"] / w["obs"], 4) if w["obs"] else None,
                    "provisional": True,
                    "experimental": True,
                    "in_progress": True,
                }
                if not series:
                    series = [{"t": w_key, "activity": latest["activity_norm"],
                               "spread": latest["spread_norm"], "surface": latest["surface_occ"]}]
    base = baseline()
    return {"provisional": True, "experimental": True,
            "latest": latest, "series": series,
            "baseline": {"days": base["days"], "windows": base["windows"],
                         "hours_covered": base["hours_covered"], "ok": base["days"] >= BASELINE_DAYS},
            "anomaly": current_anomaly(now=now),
            "metrics": {"activity": "track speed / frame diagonal",
                        "spread": "mean pairwise centroid distance / diagonal",
                        "surface": "fraction of track observations in the top 15% band"},
            "disclaimer": ("Camera-based estimate (experimental). Without a dissolved-oxygen sensor "
                           "these figures are not calibrated against oxygen events; also inspect the fish visually."),
            "note": "R6 needs |z|>3 for 3 consecutive 5-minute windows (15 min)."}

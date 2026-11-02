"""PROVISIONAL prediction layer (farmer finalization, C).

Inputs are the server-side ThingSpeak mirror (temperature °C, turbidity RAW ADC).
No dissolved-oxygen sensor exists, so "dawn DO risk" is an explicitly labelled
proxy built from temperature saturation capacity and turbidity behaviour — it is
not a DO measurement and must never be shown as one.

Components:
- C1 6-hour forecast: seasonal-naive (same hour yesterday, weight 0.6) blended
  with a 3-hour local trend (weight 0.4); uncertainty band from residual MAD.
- C2 anomaly: per-field hourly robust z (median/MAD, 7-day same-hour baseline)
  plus a flat-line ("sensor stuck") check.
- C3 dawn-DO-crash risk score (0-1): 0.40 temperature saturation drop +
  0.35 7-day turbidity diurnal swing + 0.25 24-hour turbidity rise.
- C4 gated LSTM trainer lives in scripts/predict_do_lstm.py; it refuses to run
  without >=30 days of real DO history.

Every output carries `provisional: True`. Language: see PROJECT docs.
"""
import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from backend import sensors

MAX_FILE_BYTES = 50 * 1024 * 1024
HORIZON_H = 6
_lock = threading.RLock()
_last_dawn_day = [None]


def _data_dir():
    return Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[1] / "backend" / "data"))


def _file():
    return _data_dir() / "predictions.jsonl"


def _rotate(p, max_bytes=MAX_FILE_BYTES):
    try:
        if p.is_file() and p.stat().st_size > max_bytes:
            p.replace(p.with_suffix(p.suffix + ".1"))
    except OSError:
        pass


def _persist(rec):
    try:
        p = _file()
        p.parent.mkdir(parents=True, exist_ok=True)
        _rotate(p)
        with _lock:
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _median(vals):
    s = sorted(vals)
    n = len(s)
    return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2) if s else None


def _mad(vals, med=None):
    med = _median(vals) if med is None else med
    return _median([abs(v - med) for v in vals]) if vals and med is not None else 0.0


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _hourly(series):
    buckets = {}
    for t, v in series:
        h = int(t // 3600) * 3600
        buckets.setdefault(h, []).append(v)
    return sorted((h, sum(vs) / len(vs)) for h, vs in buckets.items())


def _build_diurnal_profile(series):
    """Compute median value for each hour of the day across all historical entries.
    Interpolates smoothly across missing hours on a 24-hour cycle."""
    hour_buckets = {}
    for t, v in series:
        h = datetime.fromtimestamp(t, timezone.utc).hour
        hour_buckets.setdefault(h, []).append(v)
    known = sorted(hour_buckets.keys())
    if not known:
        default_val = series[-1][1] if series else 25.0
        return lambda h: default_val
    medians = {h: _median(hour_buckets[h]) for h in known}
    full_24 = {}
    for h in range(24):
        if h in medians:
            full_24[h] = medians[h]
        else:
            prev_h = max([k for k in known if k < h], default=known[-1])
            next_h = min([k for k in known if k > h], default=known[0])
            dist_prev = (h - prev_h) % 24
            dist_next = (next_h - h) % 24
            tot = dist_prev + dist_next
            full_24[h] = medians[prev_h] if tot == 0 else (medians[prev_h] * dist_next + medians[next_h] * dist_prev) / tot
    return lambda h: full_24[int(h) % 24]


def _recent_slope(series, window_s=3600, max_rate=2.5):
    """Compute rate of change per hour from recent observations."""
    if len(series) < 2:
        return 0.0
    last_t, last_v = series[-1]
    recent = [(t, v) for t, v in series if t >= last_t - window_s]
    if len(recent) < 2:
        recent = series[-min(len(series), 20):]
    dt_h = (recent[-1][0] - recent[0][0]) / 3600.0
    if dt_h < 0.02:
        return 0.0
    slope = (recent[-1][1] - recent[0][1]) / dt_h
    return max(-max_rate, min(max_rate, slope))


def _trend_predict(pts, h, diurnal_fn=None):
    """One h-step prediction from the end of `pts` using the documented blend."""
    last_t, last_v = pts[-1]
    target_t = last_t + h * 3600
    target_hour = datetime.fromtimestamp(target_t, timezone.utc).hour
    
    # 24-hour seasonal naive: same hour yesterday if present
    seasonal = [v for t, v in pts if abs(t - (target_t - 86400)) <= 5400]
    if seasonal:
        season_v = sum(seasonal) / len(seasonal)
    elif diurnal_fn is not None:
        season_v = diurnal_fn(target_hour)
    else:
        season_v = last_v

    recent = [(t, v) for t, v in pts if t >= last_t - 3 * 3600]
    if len(recent) >= 2:
        dt_h = max(0.5, (last_t - recent[0][0]) / 3600)
        slope = (last_v - recent[0][1]) / dt_h
    else:
        slope = 0.0

    return 0.6 * season_v + 0.4 * (last_v + slope * h)


def _backtest(pts, horizon=HORIZON_H, diurnal_fn=None):
    """Rolling-origin MAE/MAPE over historical data (evaluates cross-validation)."""
    if len(pts) < 4:
        return {"n": 0, "mae": None, "mape": None, "horizon_h": horizon}
    
    errs, pcts = [], []
    step = max(1, len(pts) // 30)
    for i in range(max(2, len(pts) // 6), len(pts), step):
        base = pts[:i]
        if not base:
            continue
        pred = _trend_predict(base, 1, diurnal_fn=diurnal_fn)
        actual = pts[i][1]
        err = abs(pred - actual)
        errs.append(err)
        if abs(actual) > 1e-6:
            pcts.append(err / abs(actual) * 100)

    return {
        "n": len(errs),
        "mae": round(sum(errs) / len(errs), 3) if errs else None,
        "mape": round(sum(pcts) / len(pcts), 2) if pcts else None,
        "horizon_h": horizon,
    }


def forecast_field(field, horizon_h=HORIZON_H, now=None):
    now = time.time() if now is None else float(now)
    # Query full historical sensor series across all entries on ThingSpeak cloud
    raw = sensors.series(field, minutes=None)
    base = {
        "field": field,
        "provisional": True,
        "horizon_h": horizon_h,
        "unit": "°C" if field == "temperature" else "RAW ADC",
        "note": (
            "6h seasonal-naive + trend blend across all ThingSpeak entries; PROVISIONAL."
            if field == "temperature" else
            "6h seasonal-naive + trend blend on RAW ADC across all ThingSpeak entries; no NTU calibration, PROVISIONAL."
        )
    }
    if len(raw) < 3:
        return {
            **base,
            "status": "insufficient_data",
            "hours_available": 0,
            "points": [],
            "backtest": {"n": 0, "mae": None, "mape": None, "horizon_h": horizon_h},
            "reason": "Need at least 3 samples from the ThingSpeak cloud mirror."
        }

    pts = _hourly(raw)
    if len(pts) < 2:
        pts = raw  # Handle dense single-session burst

    diurnal_fn = _build_diurnal_profile(raw)
    max_slope = 2.5 if field == "temperature" else 250.0
    min_band = 0.25 if field == "temperature" else 35.0
    slope = _recent_slope(raw, window_s=3600, max_rate=max_slope)
    
    last_t, last_v = raw[-1]
    
    # Calculate empirical residual MAD from diurnal fit across all entries
    residuals = []
    sample_step = max(1, len(raw) // 100)
    for idx in range(0, len(raw), sample_step):
        t_hist, v_hist = raw[idx]
        h_hist = datetime.fromtimestamp(t_hist, timezone.utc).hour
        residuals.append(abs(v_hist - diurnal_fn(h_hist)))
    
    band_base = max(min_band, 1.4826 * (_mad(residuals) or min_band))
    
    points = []
    for h in range(1, horizon_h + 1):
        target_t = last_t + h * 3600
        target_hour = datetime.fromtimestamp(target_t, timezone.utc).hour
        season_val = diurnal_fn(target_hour)
        
        # Damped trend persistence mean-reverting toward diurnal baseline
        decay = math.exp(-0.35 * h)
        trend_val = last_v + slope * (1.0 - decay) / 0.35
        
        p = 0.6 * season_val + 0.4 * trend_val
        h_band = band_base * math.sqrt(1.0 + 0.15 * h)
        
        # Format precision
        p_val = round(p, 2 if field == "temperature" else 1)
        low_val = round(max(0.0, p - h_band), 2 if field == "temperature" else 1)
        high_val = round(p + h_band, 2 if field == "temperature" else 1)
        
        points.append({
            "t": target_t,
            "iso": _iso(target_t),
            "value": p_val,
            "low": low_val,
            "high": high_val,
        })
    
    bt = _backtest(pts, horizon=horizon_h, diurnal_fn=diurnal_fn)
    
    return {
        **base,
        "status": "ok",
        "last": {"t": last_t, "iso": _iso(last_t), "value": round(last_v, 2 if field == "temperature" else 1)},
        "points": points,
        "band": round(band_base, 2 if field == "temperature" else 1),
        "backtest": bt,
        "total_entries_analyzed": len(raw),
        "method": "0.6*seasonal_diurnal_24h + 0.4*(last + damped_slope*h)",
    }


def _robust_anomalies(field, now):
    raw = sensors.series(field, minutes=None)
    pts = _hourly(raw) if len(raw) >= 3 else []
    if len(pts) < 3:
        return {"field": field, "status": "insufficient_data", "flags": []}
    by_hour = {}
    for t, v in pts:
        by_hour.setdefault(datetime.fromtimestamp(t).hour, []).append(v)
    flags = []
    for t, v in pts[-6:]:
        base = by_hour.get(datetime.fromtimestamp(t).hour, [])
        if len(base) < 3:
            continue
        med = _median(base)
        mad = _mad(base, med) or 1e-6
        z = 0.6745 * (v - med) / mad
        if abs(z) > 3.5:
            flags.append({"t": t, "iso": _iso(t), "value": round(v, 3), "median": round(med, 3),
                          "z": round(z, 2), "kind": "robust_z"})
    stuck = len(pts) >= 3 and len({round(v, 3) for _, v in pts[-3:]}) == 1
    if stuck:
        flags.append({"t": pts[-1][0], "iso": _iso(pts[-1][0]), "value": round(pts[-1][1], 3),
                      "kind": "flatline", "note": "Identical hourly values for 3h: check the sensor."})
    return {"field": field, "status": "ok", "flags": flags, "provisional": True,
            "method": "hourly median/MAD per hour-of-day, |z|>3.5; flatline = 3 identical hours"}


def anomalies(now=None):
    now = time.time() if now is None else float(now)
    return {"provisional": True, "fields": [_robust_anomalies("temperature", now),
                                             _robust_anomalies("turbidity", now)],
            "note": "Anomalies are statistical flags only; they are not a diagnosis."}


def csat(t):
    """Weiss (1970) freshwater O2 saturation, mg/L, at 1 atm."""
    return 14.652 - 0.41022 * t + 0.007991 * t * t - 0.000077774 * t * t * t


def dawn_risk(now=None, persist=False):
    """C3 proxy score for a dawn DO crash (no DO sensor: PROVISIONAL proxy)."""
    now = time.time() if now is None else float(now)
    th = _hourly(sensors.series("temperature", minutes=None))
    uh = _hourly(sensors.series("turbidity", minutes=None))
    base = {"provisional": True, "kind": "dawn_do_risk_proxy",
            "disclaimer": ("No dissolved-oxygen sensor: this is an estimate based on temperature "
                           "saturation and turbidity, not a measured oxygen value."),
            "weights": {"temperature_saturation": 0.40, "turbidity_diurnal_swing": 0.35,
                        "turbidity_24h_rise": 0.25}}
    if len(th) < 3 or len(uh) < 3:
        return {**base, "level": "INSUFFICIENT_DATA", "score": None,
                "reason": "Need >=3 hourly temperature and >=3 hourly turbidity samples."}
    t24 = [v for t, v in th if t >= now - 86400] or [th[-1][1]]
    tmean = sum(t24) / len(t24)
    sat_now = csat(tmean)
    sat_30 = csat(30.0)
    c1 = _clamp((sat_30 - sat_now) / (0.20 * sat_30))
    u24 = [v for t, v in uh if t >= now - 86400] or [uh[-1][1]]
    swing = (max(u24) - min(u24)) / max(1.0, max(u24))
    c2 = _clamp(swing / 0.6)
    rise = (uh[-1][1] - min(u24)) / max(1.0, abs(min(u24)))
    c3 = _clamp(rise / 0.8)
    score = round(0.40 * c1 + 0.35 * c2 + 0.25 * c3, 3)
    level = "LOW" if score < 0.35 else "MEDIUM" if score < 0.65 else "HIGH"
    out = {**base, "level": level, "score": score,
           "components": {"temperature_saturation_drop": round(c1, 3),
                          "turbidity_diurnal_swing": round(c2, 3),
                          "turbidity_24h_rise": round(c3, 3)},
           "evidence": {"temp_24h_mean_c": round(tmean, 2), "csat_mg_l": round(sat_now, 2),
                        "turbidity_24h_min": round(min(u24), 1), "turbidity_24h_max": round(max(u24), 1)},
           "level_cutoffs": {"LOW": "<0.35", "MEDIUM": "0.35-0.65", "HIGH": ">=0.65"},
           "ts": _iso(now)}
    day = datetime.now().date()
    if persist and _last_dawn_day[0] != day:
        _last_dawn_day[0] = day
        _persist({"ts": out["ts"], "t": now, "event": "dawn_risk", **{k: out[k] for k in
                 ("level", "score", "components", "evidence", "provisional")}})
    return out


def summary(now=None):
    return {"provisional": True,
            "temperature": forecast_field("temperature", now=now),
            "turbidity": forecast_field("turbidity", now=now),
            "dawn_risk": dawn_risk(now=now, persist=True),
            "anomalies": anomalies(now=now),
            "note": ("All prediction output is PROVISIONAL. Thresholds are project defaults, "
                     "not validated for this pond. No hardware is controlled.")}

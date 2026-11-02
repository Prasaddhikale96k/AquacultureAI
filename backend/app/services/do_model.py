"""Dissolved-oxygen physics estimate (Track II D1).

Pure functions only: no I/O, no threads, no mutable module state.

Saturation uses the Benson & Krause (1980/1984) freshwater formulation as
refit by Garcia & Gordon (1992). The older Weiss polynomial in
backend/predict.py is frozen and is NOT used here.

Source anchors (freshwater, sea level, mg/L):
0 C = 14.62, 10 C = 11.28, 20 C = 9.09, 25 C = 8.24, 28 C = 7.81,
30 C = 7.56, 35 C = 6.93.

This is always a PROVISIONAL estimate, never a measurement.
"""
from __future__ import annotations

import math
import os

# R-1: Benson & Krause freshwater saturation, Garcia & Gordon fit.
BK_C0 = -139.34411
BK_C1 = 1.575701e5
BK_C2 = 6.642308e7
BK_C3 = 1.243800e10
BK_C4 = 8.621949e11
TEMP_MIN_C = 0.0
TEMP_MAX_C = 40.0

# Altitude correction used by field calculators (Nagpur default 310 m).
ALT_FACTOR_PER_M = 0.0001184
DEFAULT_ALT_M = 310.0

# R-3: conservative RAS diurnal amplitude, scaled by turbidity.
AMP_BASE = 0.12
AMP_NTU_GAIN = 0.20
AMP_NTU_FULL = 60.0
S_MID = 0.72
DAWN_HOUR = 5.5

# STEP 3 corrections.
PH_NEUTRAL = 7.8
S_PH_COEF = 0.04
S_PH_MIN = -0.12
S_PH_MAX = 0.08
S_DT_ROSE = -0.05
S_FEED_MIN = -0.08

# STEP 4 clamps.
S_MIN = 0.30
S_MAX = 1.50
DO_MIN = 0.0
DO_MAX = 20.0

# R-4: tilapia risk bands.
SAFE_MGL = 5.0
WARN_MGL = 3.5
CRIT_MGL = 2.0
BAND_MIN = 0.6
BAND_FRACTION = 0.12

MODEL_VERSION = "do-physics-v1"


def _env_float(name, default):
    try:
        v = float(os.environ.get(name, ""))
        return v if math.isfinite(v) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _num(v, default=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _altitude_m(alt_m=None):
    alt = _num(alt_m, None)
    if alt is None:
        alt = _env_float("AQUA_ALTITUDE_M", DEFAULT_ALT_M)
    return max(0.0, alt)


def do_saturation(t_c, alt_m=None):
    """Benson & Krause freshwater O2 saturation in mg/L at 1 atm.

    `t_c` is clamped to the published 0-40 C validity window. `alt_m`
    defaults to AQUA_ALTITUDE_M (310 m for Nagpur).
    """
    t = _num(t_c, None)
    if t is None:
        return None
    t = _clamp(t, TEMP_MIN_C, TEMP_MAX_C)
    tk = t + 273.15
    ln_c = (BK_C0
            + BK_C1 / tk
            - BK_C2 / (tk ** 2)
            + BK_C3 / (tk ** 3)
            - BK_C4 / (tk ** 4))
    c_sat = math.exp(ln_c)
    return max(0.0, c_sat * (1.0 - _altitude_m(alt_m) * ALT_FACTOR_PER_M))


def risk_band(do_mgl, warn_mgl=None, crit_mgl=None):
    """Tilapia risk band. 5.0 -> safe, 4.9/3.5 -> watch, 3.4/2.0 -> risk."""
    do = _num(do_mgl, None)
    if do is None:
        return None
    warn = _env_float("AQUA_DO_WARN_MGL", WARN_MGL) if warn_mgl is None else float(warn_mgl)
    crit = _env_float("AQUA_DO_CRIT_MGL", CRIT_MGL) if crit_mgl is None else float(crit_mgl)
    if do >= SAFE_MGL:
        return "safe"
    if do >= warn:
        return "watch"
    if do >= crit:
        return "risk"
    return "critical"


def estimate_do(temp, ntu, ph, hour, dT_2h, s_feed=0.0, cal=None):
    """Estimate DO from temperature, turbidity and manual pH.

    `cal` is an optional {'a', 'b', 'n'} least-squares correction applied
    after STEP 4. Missing pH falls back to 7.8 and drops confidence.
    """
    t = _num(temp, None)
    n = _num(ntu, None)
    if t is None or n is None:
        return {"status": "invalid_inputs", "reason": "temperature and turbidity are required"}

    h = _num(hour, 0.0)
    csat = do_saturation(t)
    amp = AMP_BASE + AMP_NTU_GAIN * _clamp(n / AMP_NTU_FULL, 0.0, 1.0)
    s_base = S_MID - amp * math.cos(2.0 * math.pi * (h - DAWN_HOUR) / 24.0)

    ph_num = _num(ph, None)
    ph_defaulted = ph_num is None
    ph_used = PH_NEUTRAL if ph_defaulted else _clamp(ph_num, 0.0, 14.0)
    s_ph = _clamp(S_PH_COEF * (ph_used - PH_NEUTRAL), S_PH_MIN, S_PH_MAX)

    dt = _num(dT_2h, 0.0)
    s_dt = S_DT_ROSE if dt > 0.5 else 0.0

    feed = _num(s_feed, 0.0)
    s_feed_used = _clamp(feed, S_FEED_MIN, 0.0)

    s_before_cal = _clamp(s_base + s_ph + s_dt + s_feed_used, S_MIN, S_MAX)
    do_raw = _clamp(csat * s_before_cal, DO_MIN, DO_MAX)

    a = _num((cal or {}).get("a"), None) if isinstance(cal, dict) else None
    b = _num((cal or {}).get("b"), None) if isinstance(cal, dict) else None
    cal_applied = a is not None and b is not None
    do_value = _clamp(a * do_raw + b, DO_MIN, DO_MAX) if cal_applied else do_raw

    confidence = "medium" if cal_applied else "low"
    if ph_defaulted and confidence == "medium":
        confidence = "low"

    band = max(BAND_MIN, BAND_FRACTION * csat)
    return {
        "status": "ok",
        "do_mgl": round(do_value, 1),
        "band_low": round(max(DO_MIN, do_value - band), 1),
        "band_high": round(min(DO_MAX, do_value + band), 1),
        "percent_saturation": round(100.0 * s_before_cal),
        "do_sat_mgl": round(csat, 2),
        "s_factor": round(s_before_cal, 2),
        "risk_level": risk_band(do_value),
        "confidence": confidence,
        "label_provisional": confidence != "high",
        "components": {
            "s_base": round(s_base, 4),
            "s_ph": round(s_ph, 4),
            "s_dt": round(s_dt, 4),
            "s_feed": round(s_feed_used, 4),
            "amp": round(amp, 4),
            "ph_used": round(ph_used, 2),
            "ph_defaulted": ph_defaulted,
            "cal_applied": cal_applied,
        },
        "model_version": MODEL_VERSION,
    }

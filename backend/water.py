"""Manual water-quality input, a transparent rule engine, storage, and the combined evidence report.

Everything here is RULE-BASED screening against the configurable thresholds in water_rules.json (which reads the
project's water_quality_config.json for the base normal ranges). It is not a trained or validated predictive model,
and it never diagnoses disease. Video results never enter the water-quality risk calculation.
"""
import json
import math
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from backend import history as _history

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RULES_PATH = Path(os.environ.get("AQUA_WATER_RULES", HERE / "water_rules.json"))
LEVELS = ["normal", "warning", "high_concern", "critical_concern"]
NAME_RE = re.compile(r"^[\w .\-]{1,64}$")
ID_RE = re.compile(r"^[0-9a-f]{32}$")
_lock = threading.RLock()
_ctx = {"data": HERE / "data", "job_result": lambda job_id: (None, "no job store")}


def init(data_dir, job_result):
    _ctx["data"], _ctx["job_result"] = Path(data_dir), job_result


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__(str(errors))
        self.errors = errors


# ---------------------------------------------------------------- rules (re-read on every call, so edits apply without a restart)
def load_rules():
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    base = json.loads((ROOT / rules["base_config"]).read_text(encoding="utf-8"))
    for prof in rules["profiles"].values():
        for p in prof["parameters"].values():
            if "from_config" in p["normal"]:
                p["normal"] = dict(base[p["normal"]["from_config"]])
        for ov in prof.get("system_overrides", {}).values():
            for p in ov.values():
                if p and "normal" in p and "from_config" in p["normal"]:
                    p["normal"] = dict(base[p["normal"]["from_config"]])
    return rules


# ---------------------------------------------------------------- validation + unit handling
def _number(v):
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    if isinstance(v, bool):
        raise ValueError("must be a number")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError("must be a number")
    if not math.isfinite(x):
        raise ValueError("must be a finite number")
    return x


def to_canonical(param, value, unit, rules):
    if param == "temperature":
        return (value - 32) * 5 / 9 if unit == "F" else value
    return value * rules["units"][param][unit]


def parse_time(s):
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("must be an ISO date-time")
    if t.tzinfo is None:
        raise ValueError("must include a timezone offset (e.g. 2026-10-15T10:00:00Z)")
    return t.astimezone(timezone.utc)


def validate(payload, rules, now, known_ids=None):
    """Return a clean record or raise ValidationError({field: message}). Missing optional measurements stay absent."""
    errs, opts = {}, rules["options"]
    if not isinstance(payload, dict):
        raise ValidationError({"body": "Send a JSON object."})
    tank = str(payload.get("tankId") or "").strip()
    if not NAME_RE.match(tank):
        errs["tankId"] = "Required: 1-64 letters, digits, spaces, '.', '_' or '-'."
    for key in ("species", "system", "source"):
        if payload.get(key) not in opts[key]:
            errs[key] = f"Required. One of: {', '.join(opts[key])}."
    stage = payload.get("lifeStage") or None
    if stage is not None and stage not in opts["lifeStage"]:
        errs["lifeStage"] = f"One of: {', '.join(opts['lifeStage'])}."
    ts = None
    try:
        ts = parse_time(payload.get("timestamp"))
        if ts > now + timedelta(minutes=5):
            errs["timestamp"] = "Measurement time is in the future."
        elif ts < now - timedelta(days=3650):
            errs["timestamp"] = "Measurement time is implausibly old."
    except ValueError as e:
        errs["timestamp"] = f"Required; {e}."
    sup = payload.get("supersedes") or None
    if sup is not None and (not ID_RE.match(str(sup)) or (known_ids is not None and sup not in known_ids)):
        errs["supersedes"] = "Must be the id of an existing reading for this tank."
    raw = payload.get("measurements")
    meas = {}
    if not isinstance(raw, dict):
        errs["measurements"] = "Provide at least one measurement."
        raw = {}
    for name, m in raw.items():
        if name not in rules["units"]:
            errs[name] = "Unknown measurement."
            continue
        m = m if isinstance(m, dict) else {"value": m}
        try:
            value = _number(m.get("value"))
        except ValueError as e:
            errs[name] = f"Value {e}."
            continue
        if value is None:
            continue                                    # left empty: stays missing, never becomes 0
        unit = m.get("unit") or next(iter(rules["units"][name]))
        if unit not in rules["units"][name]:
            errs[name] = f"Unit '{unit}' not supported. One of: {', '.join(rules['units'][name])}."
            continue
        canon = to_canonical(name, value, unit, rules)
        lo, hi = rules["plausible"][name]
        if not lo <= canon <= hi:
            errs[name] = f"Not physically plausible ({lo} to {hi} {rules['canonical_units'][name]} after conversion). Check the value and unit."
            continue
        entry = {"value": value, "unit": unit, "canonicalValue": canon}
        if name == "ammonia":
            if m.get("method") not in opts["ammoniaMethod"]:
                errs["ammonia"] = f"Measurement method required. One of: {', '.join(opts['ammoniaMethod'])}."
                continue
            entry["method"] = m["method"]
        meas[name] = entry
    if not meas and "measurements" not in errs and not any(k in errs for k in raw):
        errs["measurements"] = "Provide at least one measurement."
    if errs:
        raise ValidationError(errs)
    return {"id": uuid.uuid4().hex, "createdAt": now.isoformat(), "tankId": tank, "species": payload["species"],
            "lifeStage": stage, "system": payload["system"], "timestamp": ts.isoformat(), "source": payload["source"],
            "supersedes": sup, "measurements": meas}


# ---------------------------------------------------------------- storage (append-only JSON lines; edits add a record that supersedes)
def _file():
    return _ctx["data"] / "water_readings.jsonl"


def read_all():
    out, skipped = [], 0
    with _lock:
        if _file().is_file():
            for line in _file().read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    skipped += 1
    return out, skipped


def append(record):
    with _lock:
        _file().parent.mkdir(parents=True, exist_ok=True)
        with _file().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def current_records(records, tank):
    """Records of one tank that have not been superseded by an edit, oldest first."""
    mine = [r for r in records if r["tankId"] == tank]
    gone = {r["supersedes"] for r in mine if r.get("supersedes")}
    return sorted((r for r in mine if r["id"] not in gone), key=lambda r: (r["timestamp"], r["createdAt"]))


def _sensor_fill(record, now):
    """Assessment-only copy: fill a missing temperature from a fresh sensor.

    Turbidity is deliberately NOT filled: the ThingSpeak value is raw ADC,
    not NTU, and water_rules.json thresholds are in NTU.
    """
    try:
        from backend import sensors
        pts = [(float(t), float(v)) for t, v in sensors.series("temperature", 60)
               if isinstance(v, (int, float)) and 0 <= now.timestamp() - float(t) <= 20 * 60]
    except Exception:
        return record
    if not pts or "temperature" in (record.get("measurements") or {}):
        return record
    value = round(pts[-1][1], 2)
    out = dict(record)
    out["measurements"] = dict(record.get("measurements") or {})
    out["measurements"]["temperature"] = {"value": value, "unit": "C",
                                          "canonicalValue": value, "source": "sensor"}
    return out


def assessed_records(records, tank, now):
    """Current records with the latest one sensor-augmented for rule assessment."""
    cur = current_records(records, tank)
    if not cur:
        return cur
    return cur[:-1] + [_sensor_fill(cur[-1], now)]


# ---------------------------------------------------------------- engine
def unionized_fraction(ph, temp_c):
    pka = 0.09018 + 2729.92 / (temp_c + 273.15)          # Emerson et al. 1975 (freshwater)
    return 1 / (1 + 10 ** (pka - ph))


def do_saturation(temp_c):                                  # freshwater, sea level (common polynomial fit)
    return max(0.1, 14.652 - 0.41022 * temp_c + 0.007991 * temp_c ** 2 - 0.000077774 * temp_c ** 3)


def _fmt(x):
    return f"{x:g}"


def evaluate(value, rule):
    """Return (level, direction, threshold, band) for one value. 'above' is exclusive; normal range is inclusive."""
    for level in ("critical_concern", "high_concern"):
        b = rule["bands"].get(level, {})
        if "below" in b and value < b["below"]:
            return level, "below", b["below"], level
        if "above" in b and value > b["above"]:
            return level, "above", b["above"], level
    n = rule["normal"]
    if n.get("min") is not None and value < n["min"]:
        return "warning", "below", n["min"], "normal range"
    if n.get("max") is not None and value > n["max"]:
        return "warning", "above", n["max"], "normal range"
    return "normal", None, None, None


def _rule_for(profile, system, key):
    ov = profile.get("system_overrides", {}).get(system, {})
    base = profile["parameters"].get(key)
    if key in ov:                                            # None means: not assessed for this system
        return None if ov[key] is None else {**base, **ov[key]}
    return base


def _derived_value(param, rec):
    """Value actually compared with the rule for this record: for ammonia, the calculated un-ionized fraction."""
    m = rec["measurements"][param]
    if param != "ammonia":
        return m["canonicalValue"], {}
    t, p = rec["measurements"].get("temperature"), rec["measurements"].get("pH")
    if not t or not p:
        return None, {}
    f = unionized_fraction(p["canonicalValue"], t["canonicalValue"])
    return m["canonicalValue"] * f, {"unionizedFraction": round(f, 5), "unionizedAmmoniaN": m["canonicalValue"] * f,
                                     "pH": p["canonicalValue"], "temperatureC": t["canonicalValue"]}


def _level_for(param, rec, profile, system):
    key = "unionizedAmmonia" if param == "ammonia" else param
    rule = _rule_for(profile, system, key)
    if rule is None:
        return "not_assessed", None, rule, key, {}
    value, derived = _derived_value(param, rec)
    if value is None:
        return "insufficient_data", None, rule, key, derived
    return evaluate(value, rule), value, rule, key, derived


def _label(param, rules):
    if param == "ammonia":
        return "Total ammonia"
    return next((p["parameters"][param]["label"] for p in rules["profiles"].values() if param in p["parameters"]), param)


def assess_water(records, rules, now):
    """Assessment of the tank's current (non-superseded) readings. Takes NO video input by design."""
    if not records:
        return None
    latest = records[-1]
    species, system = latest["species"], latest["system"]
    profile = rules["profiles"].get(species)
    out = {"tankId": latest["tankId"], "species": species, "system": system, "lifeStage": latest["lifeStage"],
           "generatedAt": now.isoformat(), "rulesStatus": rules["status"], "kind": "rule_based_screening",
           "profile": profile["label"] if profile else None, "lifeStageNote": profile.get("lifeStageNote") if profile else None,
           "measurements": [], "concerns": [], "notes": [], "inputs": []}
    seen = set()
    for param in rules["units"]:
        recs = [r for r in records if param in r["measurements"]]
        item = {"parameter": param, "label": _label(param, rules),
                "unit": rules["canonical_units"][param], "level": "insufficient_data", "dataQuality": "missing",
                "value": None, "message": "Not measured. A missing measurement does not mean the value is acceptable.",
                "check": [], "actions": [], "rule": None, "confirmed": None, "persistence": 0}
        if recs:
            r = recs[-1]
            m = r["measurements"][param]
            age = (now - datetime.fromisoformat(r["timestamp"])).total_seconds() / 3600
            item.update(value=m["canonicalValue"], enteredValue=m["value"], enteredUnit=m["unit"], timestamp=r["timestamp"],
                        source=m.get("source") or r["source"], recordId=r["id"], ageHours=round(age, 1), dataQuality="ok")
            if param == "ammonia":
                item["method"] = m["method"]
            if r["id"] not in seen:
                seen.add(r["id"])
                out["inputs"].append({"recordId": r["id"], "timestamp": r["timestamp"], "source": r["source"]})
            limit = rules["stale_after_hours"][param]
            if age > limit:
                item.update(dataQuality="stale", message=f"Last measured {age:.0f} h ago (limit {limit} h); not treated as current.")
            elif param == "dissolvedOxygen" and "temperature" in r["measurements"] and m["canonicalValue"] > 1.5 * do_saturation(r["measurements"]["temperature"]["canonicalValue"]):
                item.update(dataQuality="contradictory", message="Dissolved oxygen is far above saturation for the recorded temperature (check units, calibration and temperature).")
            elif not profile:
                item.update(message=f"No rules are configured for species '{species}'; only plausibility checks were applied.")
            else:
                level, value, rule, key, derived = _level_for(param, r, profile, system)
                if level == "not_assessed":
                    item.update(level="not_assessed", message=f"Not assessed for system '{system}' (rule disabled in configuration).")
                elif level == "insufficient_data":
                    item.update(message="Un-ionized ammonia needs pH and temperature in the SAME reading; they were not provided.")
                else:
                    lv, direction, thr, band = level
                    item.update(level=lv, derived=derived or None, group=rule["group"], check=rule["check"], rule=None)
                    # persistence: earlier readings of this parameter inside the confirmation window
                    window = timedelta(hours=rules["confirm_window_hours"])
                    prior = [p for p in recs[:-1] if datetime.fromisoformat(r["timestamp"]) - datetime.fromisoformat(p["timestamp"]) <= window]
                    n = 0
                    for p in reversed(prior):
                        pl = _level_for(param, p, profile, system)[0]
                        if pl in ("not_assessed", "insufficient_data") or pl[0] == "normal":
                            break
                        n += 1
                    item["persistence"] = n
                    if lv == "normal":
                        item["message"] = f"{_fmt(round(value, 4))} {rule['unit']} is within the configured normal range."
                    else:
                        item.update(rule={"id": f"{key}.{lv}.{direction}", "direction": direction, "threshold": thr, "band": band,
                                          "provisional": True},
                                    actions=rule["actions"][lv], confirmed=n >= 1 if lv in ("high_concern", "critical_concern") else None)
                        where = "outside the normal range" if band == "normal range" else f"{band.replace('_', ' ')} threshold"
                        item["message"] = f"{rule['label']} {_fmt(round(value, 4))} {rule['unit']} is {direction} {_fmt(thr)} ({where})."
                        if lv in ("high_concern", "critical_concern") and n == 0:
                            item["message"] += " Based on a single reading: repeat the measurement to confirm."
        out["measurements"].append(item)

    concerns = [i for i in out["measurements"] if i["level"] in LEVELS[1:]]
    groups = {}
    for c in concerns:
        g = groups.setdefault(c["group"], {"group": c["group"], "level": "warning", "parameters": []})
        g["parameters"].append(c["parameter"])
        if LEVELS.index(c["level"]) > LEVELS.index(g["level"]):
            g["level"] = c["level"]
    out["concerns"] = sorted(concerns, key=lambda c: -LEVELS.index(c["level"]))
    out["concernGroups"] = list(groups.values())            # related parameters share one group, so one issue is not counted twice
    byp = {i["parameter"]: i for i in out["measurements"]}
    if "nitrogen_cycle" in groups and byp["pH"]["level"] in LEVELS[1:] and byp["pH"].get("rule", {}) and byp["pH"]["rule"]["direction"] == "above":
        out["notes"].append("High pH raises the toxic un-ionized fraction of ammonia; pH and ammonia are listed separately but reflect related conditions.")
    if "oxygen" in groups and byp["temperature"]["level"] in LEVELS[1:] and byp["temperature"].get("rule", {}) and byp["temperature"]["rule"]["direction"] == "above":
        out["notes"].append("Warm water holds less dissolved oxygen; the temperature and oxygen concerns may be related.")
    core = rules["core_parameters"]
    ok = [i for i in out["measurements"] if i["level"] in LEVELS]             # actually assessed (fresh, valid, a rule exists)
    core_ok = all(byp[p]["level"] in LEVELS for p in core)
    top = max((LEVELS.index(c["level"]) for c in concerns), default=0)
    out["waterRisk"] = LEVELS[top] if concerns else ("no_rule_triggered" if core_ok else "insufficient_data")
    out["dataQuality"] = {
        "status": "sufficient" if core_ok else ("insufficient" if not ok else "partial"),
        "missing": [i["parameter"] for i in out["measurements"] if i["dataQuality"] == "missing"],
        "stale": [i["parameter"] for i in out["measurements"] if i["dataQuality"] == "stale"],
        "contradictory": [i["parameter"] for i in out["measurements"] if i["dataQuality"] == "contradictory"],
        "coreMissingOrUnusable": [p for p in core if byp[p]["level"] not in LEVELS]}
    out["summary"] = _summary(out)
    return out


def _summary(a):
    wr = a["waterRisk"]
    if wr == "no_rule_triggered":
        return "No configured rule was triggered by the available, current measurements. This is not a statement that conditions are safe."
    if wr == "insufficient_data":
        return "Insufficient current data for a water-quality assessment: core measurements (temperature, pH, dissolved oxygen) are missing, stale or unusable."
    n = len(a["concernGroups"])
    s = f"{wr.replace('_', ' ')}: {n} distinct issue{'s' if n != 1 else ''} identified by the rules."
    if a["dataQuality"]["status"] != "sufficient":
        s += " Core data is incomplete, so other concerns may be missing."
    return s


# ---------------------------------------------------------------- combined evidence report (video never changes the water risk)
VIDEO_STATES = ("reliable", "needs_review", "unreliable", "unavailable")


def video_summary(result, reason=None):
    if not result:
        return {"available": False, "reason": reason or "No analysed video selected.", "usedInRisk": False}
    rel = result.get("reliability") or {}
    obs = []
    proc = result.get("processing") or {}
    if proc:
        obs.append(f"Processed {proc.get('framesProcessed')} of {proc.get('framesTotal')} frames ({proc.get('sampling')}).")
    obs.append("Detection counts are frame-level counts of detected regions, not unique fish, and a high confidence score does not mean a detection is correct.")
    for k in ("detections", "movement", "tracking"):
        obs.append(f"{k.capitalize()}: {rel.get(k, 'unavailable').replace('_', ' ')}.")
    for r in (result.get("detections") or {}).get("reasons", []) + (result.get("movement") or {}).get("reasons", []):
        obs.append(r)
    return {"available": True, "videoName": result.get("videoName"), "reliability": rel, "observations": obs, "usedInRisk": False,
            "processing": proc}


def combine(water, video):
    """Transparent evidence summary. Water risk comes from water measurements only; video is reported, not scored."""
    out = {"water": water, "video": video, "uncertainty": [], "crossNotes": []}
    wr = water["waterRisk"] if water else None
    if wr in ("critical_concern", "high_concern"):
        status = "action_recommended"
    elif wr == "warning":
        status = "review_recommended"
    elif wr == "no_rule_triggered":
        status = "no_rule_triggered"
    else:
        status = "insufficient_data"
    out["overallStatus"] = status
    dq = water["dataQuality"]["status"] if water else "insufficient"
    mv = (video.get("reliability") or {}).get("movement", "unavailable") if video.get("available") else "unavailable"
    out["dataQuality"] = {"water": dq, "video": "usable_with_review" if mv in ("reliable", "needs_review") else "not_usable_for_movement"}
    if not water:
        out["uncertainty"].append("No water-quality measurements are available for this tank.")
    elif dq != "sufficient":
        out["uncertainty"].append("Core water measurements are incomplete, stale or unusable; absence of a concern is not evidence of safety.")
    if not video.get("available"):
        out["uncertainty"].append("No analysed video is attached; fish behaviour was not assessed.")
    elif mv != "reliable":
        out["uncertainty"].append("Video movement metrics are not reliable for this video, so the video neither supports nor rules out stress.")
        if wr in ("warning", "high_concern", "critical_concern"):
            out["crossNotes"].append("A water-quality concern exists, but video cannot confirm any effect on the fish. Review the footage manually.")
    out["uncertainty"].append("Rule-based screening against provisional thresholds: not a diagnosis, not a trained prediction and not a probability of disease or mortality.")
    return out


# ---------------------------------------------------------------- HTTP routes
def _err(status, message, **kw):
    return JSONResponse({"error": message, **kw}, status_code=status)


def _now():
    return datetime.now(timezone.utc)


async def config(_):
    r = load_rules()
    return JSONResponse({"options": r["options"], "units": {k: list(v) for k, v in r["units"].items()}, "canonicalUnits": r["canonical_units"],
                         "plausible": r["plausible"], "rulesStatus": r["status"], "coreParameters": r["core_parameters"],
                         "staleAfterHours": r["stale_after_hours"]})


async def post_reading(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return _err(400, "Send a JSON body.")
    ph_only = False
    if isinstance(payload, dict) and "measurements" not in payload:
        raw_ph = payload.get("ph")
        if raw_ph is None:
            raw_ph = payload.get("pH")
        if raw_ph is not None:
            entry = raw_ph if isinstance(raw_ph, dict) else {"value": raw_ph}
            payload = {**payload, "measurements": {"pH": entry}}
            ph_only = True
    rules = load_rules()
    records, _ = read_all()
    tank = str((payload or {}).get("tankId") or "").strip() if isinstance(payload, dict) else ""
    try:
        rec = validate(payload, rules, _now(), known_ids={r["id"] for r in records if r["tankId"] == tank})
    except ValidationError as e:
        return _err(422, "Validation failed.", fields=e.errors)
    append(rec)
    records, _ = read_all()
    assessment = assess_water(assessed_records(records, rec["tankId"], _now()), rules, _now())
    _history.record("water_reading", tank_id=rec["tankId"], record_id=rec["id"],
                    water_risk=(assessment or {}).get("waterRisk"),
                    parameters=sorted(rec["measurements"].keys()))
    body = {"reading": rec, "assessment": assessment}
    if ph_only:
        body["ph_only"] = True
    return JSONResponse(body, status_code=201)


async def get_readings(request: Request):
    records, skipped = read_all()
    tank = request.query_params.get("tankId")
    tanks = sorted({r["tankId"] for r in records})
    if not tank:
        return JSONResponse({"tanks": tanks, "readings": [], "skippedLines": skipped})
    if not NAME_RE.match(tank):
        return _err(422, "Invalid tankId.")
    mine = [r for r in records if r["tankId"] == tank]
    gone = {r["supersedes"] for r in mine if r.get("supersedes")}
    return JSONResponse({"tanks": tanks, "skippedLines": skipped,
                         "readings": [dict(r, superseded=r["id"] in gone) for r in sorted(mine, key=lambda r: r["timestamp"], reverse=True)]})


async def get_assessment(request: Request):
    tank = request.query_params.get("tankId") or ""
    if not NAME_RE.match(tank):
        return _err(422, "Provide a valid tankId.")
    records, _ = read_all()
    a = assess_water(assessed_records(records, tank, _now()), load_rules(), _now())
    return JSONResponse(a) if a else _err(404, "No readings for this tank.")


async def get_combined(request: Request):
    tank, job = request.query_params.get("tankId") or "", request.query_params.get("jobId")
    if tank and not NAME_RE.match(tank):
        return _err(422, "Invalid tankId.")
    if job and not ID_RE.match(job):
        return _err(422, "Invalid jobId.")
    records, _ = read_all()
    water = assess_water(assessed_records(records, tank, _now()), load_rules(), _now()) if tank else None
    result, reason = _ctx["job_result"](job) if job else (None, None)
    return JSONResponse(combine(water, video_summary(result, reason)))


ROUTES = [
    Route("/api/water-config", config),
    Route("/api/water-readings", post_reading, methods=["POST"]),
    Route("/api/water-readings", get_readings),
    Route("/api/water-assessment", get_assessment),
    Route("/api/assessment", get_combined),
]

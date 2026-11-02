"""Unified operational risk engine: transparent 5-level status from verified evidence.

Severity taxonomy (documented logic, no silent upgrades):
- NORMAL: a current assessment exists, core data is sufficient, no rule triggered.
- WATCH: a warning-level rule, an unconfirmed high/critical rule, or a
  measurable data-quality degradation (stale core readings) needs observation.
- WARNING: a high_concern rule (verified evidence requiring timely investigation).
- CRITICAL: ONLY when a critical_concern rule is CONFIRMED by a repeat reading
  inside the configured confirmation window (the engine's `confirmed` flag).
  Unconfirmed critical_concern -> WARNING + "repeat to confirm".
- INSUFFICIENT_DATA: no usable water assessment (missing/stale/contradictory
  core data) and no usable video.

Domains (kept separate, never merged into one unexplained label):
1. water: from the deterministic rule engine (rule-based).
2. behavior: EXPERIMENTAL (LLM text observation); reported, never risk-driving.
3. data_quality: from reading freshness/completeness (measured).
4. video: reliability of the attached analysis (measured); NEVER changes the
   water-driven level (a bad video cannot escalate or clear water risk).
5. overall: max of water-derived level, possibly raised to WATCH by stale core
   data; INSUFFICIENT_DATA when evidence cannot support an assessment.

Thresholds are NOT set here: they come from backend/water_rules.json (which
reads water_quality_config.json). Provisional status is carried through.
No disease diagnosis, no mortality prediction, no calibrated probabilities.
"""
from datetime import datetime, timezone

LEVELS = ["NORMAL", "WATCH", "WARNING", "CRITICAL", "INSUFFICIENT_DATA"]
_WATER_MAP = {"no_rule_triggered": "NORMAL", "warning": "WATCH",
              "high_concern": "WARNING", "critical_concern": "WARNING",
              "insufficient_data": "INSUFFICIENT_DATA"}


def assess(combined):
    """combined: output of water.combine(). Returns the risk document."""
    water = (combined or {}).get("water")
    video = (combined or {}).get("video") or {}
    now = datetime.now(timezone.utc).isoformat()

    domains = {}
    evidence = []
    triggered_rules = []
    recommended_checks = []
    uncertainty = list((combined or {}).get("uncertainty", []))

    # ---- water domain (rule-based)
    if not water:
        water_level = "INSUFFICIENT_DATA"
        domains["water"] = {"level": water_level, "origin": "rule-based",
                            "detail": "No water-quality readings for this tank."}
    else:
        wr = water.get("waterRisk", "insufficient_data")
        water_level = _WATER_MAP.get(wr, "INSUFFICIENT_DATA")
        concerns = water.get("concerns", [])
        crit_confirmed = [c for c in concerns
                          if c.get("level") == "critical_concern" and c.get("confirmed")]
        crit_unconfirmed = [c for c in concerns
                            if c.get("level") == "critical_concern" and not c.get("confirmed")]
        if crit_confirmed:
            water_level = "CRITICAL"
        elif crit_unconfirmed:
            water_level = "WARNING"
            uncertainty.append("A critical-range value rests on a single reading: repeat the measurement "
                               "to confirm before treating it as urgent.")
        for m in water.get("measurements", []):
            if m.get("dataQuality") != "missing" and m.get("value") is not None:
                evidence.append({"type": "measurement", "origin": "measured",
                                 "parameter": m.get("label"), "value": m.get("value"),
                                 "unit": m.get("unit"), "level": m.get("level"),
                                 "timestamp": m.get("timestamp"),
                                 "data_quality": m.get("dataQuality")})
        for c in concerns:
            rule = c.get("rule") or {}
            triggered_rules.append({"parameter": c.get("label"), "level": c.get("level"),
                                    "rule_id": rule.get("id"), "threshold": rule.get("threshold"),
                                    "direction": rule.get("direction"),
                                    "confirmed": c.get("confirmed"),
                                    "provisional": True, "origin": "rule-based"})
            recommended_checks.extend(c.get("check", [])[:2] + c.get("actions", [])[:1])
        domains["water"] = {"level": water_level, "origin": "rule-based",
                            "water_risk": wr, "profile": water.get("profile"),
                            "rules_status": water.get("rulesStatus"),
                            "summary": water.get("summary")}

    # ---- data-quality domain (measured)
    dq_level = None
    dq_detail = "Core water data sufficient."
    if water:
        dq = water.get("dataQuality", {})
        stale_core = [p for p in dq.get("stale", []) if p in ("temperature", "pH", "dissolvedOxygen")]
        if dq.get("status") == "insufficient":
            dq_level, dq_detail = "INSUFFICIENT_DATA", "Core measurements missing or unusable."
        elif stale_core:
            dq_level, dq_detail = "WATCH", f"Core readings stale: {', '.join(stale_core)}."
        elif dq.get("status") == "partial":
            dq_level, dq_detail = "WATCH", "Core data partial; other concerns may be missing."
    domains["data_quality"] = {"level": dq_level or ("INSUFFICIENT_DATA" if water_level == "INSUFFICIENT_DATA" else "NORMAL"),
                               "origin": "measured", "detail": dq_detail}

    # ---- video domain (measured reliability; never risk-driving)
    rel = (video.get("reliability") or {}) if video.get("available") else {}
    domains["video"] = {"level": None, "origin": "measured",
                        "available": bool(video.get("available")),
                        "reliability": rel or "unavailable",
                        "used_in_risk": False,
                        "detail": ("; ".join(video.get("observations", [])[:3])
                                   if video.get("available") else video.get("reason") or "No analysed video attached.")}

    # ---- behavior domain (experimental; never risk-driving)
    domains["behavior"] = {"level": None, "origin": "experimental",
                           "detail": "No validated behavior classifier for tilapia. LLM movement "
                                     "observations (/api/behavior) are experimental and do not affect risk."}

    # ---- overall (documented combination)
    # Note: a fully stale core already yields waterRisk insufficient_data (stale
    # readings are unusable, never treated as current), so INSUFFICIENT_DATA is
    # the correct outcome there — never NORMAL, never an upgrade from stale data.
    if water_level == "INSUFFICIENT_DATA" or domains["data_quality"]["level"] == "INSUFFICIENT_DATA":
        overall = "INSUFFICIENT_DATA"
    else:
        overall = water_level
        if overall == "NORMAL" and domains["data_quality"]["level"] == "WATCH":
            overall = "WATCH"  # partial non-core gaps alongside healthy core data merit observation
    uncertainty.append("Provisional screening thresholds: not validated for this tank, system or life stage. "
                       "Review with an aquaculture specialist before acting.")
    return {
        "status": overall,
        "engine": "risk/v1 (deterministic; thresholds from water_rules.json, provisional)",
        "domains": domains,
        "evidence": evidence,
        "triggered_rules": triggered_rules,
        "recommended_checks": list(dict.fromkeys(recommended_checks))[:8],
        "uncertainty": uncertainty,
        "cross_notes": (combined or {}).get("crossNotes", []),
        "evaluated_at": now,
    }

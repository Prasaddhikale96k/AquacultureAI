"""LLM reasoning layer: Gemini (primary) + Groq (fallback), server-side only.

What this is and is NOT:
- The deterministic engines (backend/water.py, backend/risk.py) and the measured
  computer-vision outputs remain authoritative. This module only EXPLAINS the
  ALREADY COMPUTED evidence. It never overrides a risk status and never creates
  a risk unsupported by the evidence.
- It does NOT diagnose disease, does NOT predict mortality, and does NOT assign
  numerical disease probabilities. The prompts below enforce that grounding.

Provider order for text (env LLM_TEXT_ORDER, default "gemini,groq" per the
system spec §8: Gemini-powered explanations):
- Gemini: ``gemini-3.1-pro-preview`` (most accurate widely-available stable model),
  then ``gemini-3.8-flash``, then ``gemini-2.5-flash``.
- Groq fallback: ``openai/gpt-oss-120b``, then ``llama-3.3-70b-versatile``,
  then ``meta-llama/llama-4-scout-17b-16e-instruct``.
Override models with GROQ_MODEL / GEMINI_MODEL (prepended to that chain).

Keys are server-side only: GROQ_API_KEY, GEMINI_API_KEY. No key is ever
returned to the frontend or written to logs/results/history.

Zero extra dependencies: plain stdlib urllib (groq-sdk / google-generativeai
are NOT required).
"""
import hashlib
import json
import os
import re
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Best-accuracy defaults (Oct 2026). Env overrides are prepended, not replaced,
# so a bad override still falls back to these.
GROQ_DEFAULT_CHAIN = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
]
GEMINI_DEFAULT_CHAIN = [
    "gemini-3.1-pro-preview",
    "gemini-3.8-flash",
    "gemini-2.5-flash",
]

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Shared User-Agent for every Groq call (llm.py + vision.py import this one
# constant). Cloudflare in front of api.groq.com answers the bare python-urllib
# User-Agent with "403 error code: 1010" (verified 2026-08-17 via
# scripts/diagnose_vision_keys.py --groq-ua default vs custom); the same request
# with this header reaches the API (HTTP 200 on text).
GROQ_UA = "AquacultureAI/1.0"


class LlmError(Exception):
    """One provider/model attempt failed (safe message: never contains a key)."""

    def __init__(self, provider, model, message):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.message = message


class NoKeysError(LlmError):
    def __init__(self):
        super().__init__("none", "none",
                         "No LLM API key is configured. Set GROQ_API_KEY and/or GEMINI_API_KEY "
                         "as backend environment variables.")


class CooldownError(Exception):
    """A fresh explanation was requested too soon after the last one for the
    same scope with changed evidence. Carries retry_after_s + last response."""

    def __init__(self, retry_after_s, last=None):
        super().__init__(f"Explanation cooldown: retry in {retry_after_s}s.")
        self.retry_after_s = retry_after_s
        self.last = last


def text_order():
    """Ordered provider names for text tasks. Default Gemini-first (§8)."""
    raw = os.environ.get("LLM_TEXT_ORDER", "gemini,groq").lower()
    order = [p.strip() for p in raw.split(",") if p.strip() in ("gemini", "groq")]
    for p in ("gemini", "groq"):
        if p not in order:
            order.append(p)
    return order


def _timeout():
    try:
        return max(5, int(os.environ.get("LLM_TIMEOUT_S", "25")))
    except ValueError:
        return 25


def config():
    """Which providers are configured + effective model chains (no secrets)."""
    groq_key = bool(os.environ.get("GROQ_API_KEY"))
    gemini_key = bool(os.environ.get("GEMINI_API_KEY"))
    groq_chain = _chain(os.environ.get("GROQ_MODEL"), GROQ_DEFAULT_CHAIN) if groq_key else []
    gemini_chain = _chain(os.environ.get("GEMINI_MODEL"), GEMINI_DEFAULT_CHAIN) if gemini_key else []
    return {
        "groq_configured": groq_key,
        "gemini_configured": gemini_key,
        "groq_chain": groq_chain,
        "gemini_chain": gemini_chain,
        "timeout_s": _timeout(),
    }


def status():
    c = config()
    chains = {"gemini": [f"gemini:{m}" for m in c["gemini_chain"]],
              "groq": [f"groq:{m}" for m in c["groq_chain"]]}
    order = []
    for p in text_order():
        order.extend(chains[p])
    return {
        "groq_configured": c["groq_configured"],
        "gemini_configured": c["gemini_configured"],
        "groq_model": c["groq_chain"][0] if c["groq_chain"] else None,
        "gemini_model": c["gemini_chain"][0] if c["gemini_chain"] else None,
        "text_order": text_order(),
        "fallback_order": order,
    }


def _chain(override, defaults):
    out = []
    for m in ([override] if override else []) + list(defaults):
        m = (m or "").strip()
        if m and m not in out:
            out.append(m)
    return out


# ---------------------------------------------------------------- HTTP helper (stdlib only)
def _retry_after_s(headers):
    """Best-effort seconds until retry from Retry-After / x-ratelimit-reset-* (telemetry only)."""
    try:
        raw = headers.get("retry-after") if headers else None
    except Exception:
        return None
    if raw:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    for name in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        try:
            raw = headers.get(name) if headers else None
        except Exception:
            raw = None
        if raw:
            m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?", raw.strip())
            if m and (m.group(1) or m.group(2)):
                return float(m.group(1) or 0) * 60.0 + float(m.group(2) or 0)
    return None


def _post_json(url, payload, headers=None, timeout=25):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            body = ""
        err = LlmError("http", url, f"HTTP {e.code}: {body or e.reason}")
        err.status_code = e.code                                     # structured telemetry (no key, no url in message)
        err.retry_after = _retry_after_s(getattr(e, "headers", None))
        raise err from None
    except Exception as e:  # timeout, DNS, connection reset, ...
        raise LlmError("http", url, f"{type(e).__name__}: {e}"[:300])


import urllib.error  # noqa: E402  (kept after helper def for readability; stdlib)


# ---------------------------------------------------------------- providers
def call_groq(model, messages, api_key, timeout, max_tokens=900, json_mode=False):
    payload = {"model": model, "messages": messages, "temperature": 0.2 if not json_mode else 0.1,
               "max_tokens": max_tokens}
    if json_mode and (model.startswith("openai/") or "llama-3.3" in model):
        # Known JSON-mode support on Groq; other models get the JSON instruction only,
        # so an unsupported parameter can never fail the whole call.
        payload["response_format"] = {"type": "json_object"}
    code, body = _post_json(GROQ_URL, payload,
                            headers={"Authorization": f"Bearer {api_key}", "User-Agent": GROQ_UA},
                            timeout=timeout)
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LlmError("groq", model, f"Unexpected Groq response (HTTP {code}).")
    text = (text or "").strip()
    if not text:
        raise LlmError("groq", model, "Empty response from Groq.")
    return text


def call_gemini(model, system_text, user_text, api_key, timeout, max_tokens=900, json_mode=False):
    url = GEMINI_URL_TMPL.format(model=model) + "?key=" + urllib.parse.quote(api_key, safe="")
    gen = {"temperature": 0.2 if not json_mode else 0.1, "maxOutputTokens": max_tokens}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    code, body = _post_json(
        url,
        {
            "system_instruction": {"parts": [{"text": system_text}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": gen,
        },
        timeout=timeout,
    )
    try:
        parts = body["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except (KeyError, IndexError, TypeError):
        # Surface API-level error messages (e.g. bad model id) when present.
        err = (body.get("error") or {}).get("message", "") if isinstance(body, dict) else ""
        raise LlmError("gemini", model, f"Unexpected Gemini response (HTTP {code}). {err}"[:300])
    text = (text or "").strip()
    if not text:
        raise LlmError("gemini", model, "Empty response from Gemini.")
    return text


# ---------------------------------------------------------------- prompt (grounding guardrails)
SYSTEM_PROMPT = (
    "You are the AquacultureAI advisory assistant. You explain an ALREADY COMPUTED "
    "rule-based water-quality screening and video observations to a fish farmer in plain language.\n"
    "STRICT RULES:\n"
    "1. The screening result is authoritative. Never contradict its waterRisk/overallStatus.\n"
    "2. Never diagnose fish disease, never predict mortality, never give drug/chemical doses.\n"
    "3. Only use the measurements and observations given. Never invent numbers, sensors, or video findings.\n"
    "4. Missing data is not safe data: say what is missing and what to measure next.\n"
    "5. Video evidence is reported separately and NEVER changes the water risk.\n"
    "FORMAT: 3 short sections with bullets: 'What the screening found' (<=4 bullets), "
    "'What to check next' (<=4 bullets, drawn from the provided check/actions), "
    "'Limits' (1-2 bullets: provisional thresholds, need specialist review). "
    "Under 220 words. End with: 'Provisional screening only - confirm with a specialist.'"
)


def build_prompt(combined):
    """Compact the combined assessment into a grounded user prompt (capped)."""
    water = (combined or {}).get("water") or {}
    video = (combined or {}).get("video") or {}
    lines = [
        f"overallStatus={combined.get('overallStatus')}",
        f"waterRisk={water.get('waterRisk')} summary={water.get('summary')}",
        f"species={water.get('species')} system={water.get('system')} lifeStage={water.get('lifeStage')}",
    ]
    for m in water.get("measurements", []):
        if m.get("dataQuality") == "missing":
            lines.append(f"- {m.get('label')}: NOT MEASURED")
        else:
            lines.append(
                f"- {m.get('label')}: value={m.get('value')} level={m.get('level')} "
                f"quality={m.get('dataQuality')} msg={m.get('message')}"
            )
    for c in water.get("concerns", []):
        lines.append(
            f"CONCERN {c.get('label')} ({c.get('level')}): check={'; '.join(c.get('check', [])[:2])} "
            f"actions={'; '.join(c.get('actions', [])[:2])}"
        )
    lines.append(f"video_available={video.get('available')} reliability={video.get('reliability')}")
    for o in (video.get("observations") or [])[:8]:
        lines.append(f"VIDEO: {o}")
    for u in list((combined.get("uncertainty") or [])[:4]):
        lines.append(f"UNCERTAINTY: {u}")
    text = "\n".join(lines)
    return SYSTEM_PROMPT, text[:6000]


# ---------------------------------------------------------------- fallback orchestration
def _is_auth_error(message):
    m = (message or "").lower()
    return ("http 401" in m or "http 403" in m or "invalid api key" in m
            or "api key not valid" in m or "incorrect api key" in m)


def _run_text(system_text, user_text, timeout=None, max_tokens=900, json_mode=False):
    """Run one text prompt across the ordered provider chains.

    Returns (provider, model, text, tried). Raises NoKeysError / LlmError.
    json_mode requests structured JSON output where the model supports it.
    """
    cfg = config()
    keys = {"groq": os.environ.get("GROQ_API_KEY") or "",
            "gemini": os.environ.get("GEMINI_API_KEY") or ""}
    chains = {"groq": cfg["groq_chain"], "gemini": cfg["gemini_chain"]}
    timeout = cfg["timeout_s"] if timeout is None else timeout
    messages = [{"role": "system", "content": system_text},
                {"role": "user", "content": user_text}]
    tried, failures, skip = [], [], set()
    for provider in text_order():
        for model in chains[provider]:
            if provider in skip:
                break
            try:
                if provider == "groq":
                    text = call_groq(model, messages, keys["groq"], timeout,
                                     max_tokens=max_tokens, json_mode=json_mode)
                else:
                    text = call_gemini(model, system_text, user_text, keys["gemini"], timeout,
                                       max_tokens=max_tokens, json_mode=json_mode)
                return provider, model, text, tried
            except LlmError as e:
                tried.append(f"{provider}:{model}")
                failures.append(f"{provider}:{model} -> {e.message}"[:200])
                if _is_auth_error(e.message):
                    skip.add(provider)  # same key for the whole chain: don't repeat
    if not tried:
        raise NoKeysError()
    raise LlmError("all", "all",
                   "All LLM attempts failed: " + " | ".join(failures)[:600])


def advise(combined):
    """Plain-language explanation of the combined assessment.

    Provider order follows LLM_TEXT_ORDER (default Gemini, then Groq).
    Returns dict with provider trace. Raises NoKeysError / LlmError.
    """
    system_text, user_text = build_prompt(combined)
    provider, model, text, tried = _run_text(system_text, user_text)
    return _ok(provider, model, text, tried)


def _ok(provider, model, text, tried):
    return {
        "provider": provider,
        "model": model,
        "advice": text,
        "fallback_used": len(tried) > 0,  # first attempt is index 0; any prior failure = fallback
        "tried": list(tried),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------- behavior observation (replaces the RandomForest classifier)
BEHAVIOR_SYSTEM = (
    "You are an AquacultureAI behavior observer. You describe a SINGLE fish track's movement "
    "from its computed statistics. This replaces a previous experimental classifier and is itself "
    "experimental and unvalidated: it must never diagnose disease, stress or health, and never "
    "predict mortality.\n"
    "STRICT RULES:\n"
    "1. Use ONLY the statistics given. Never invent speeds, durations or events.\n"
    "2. Describe only observable movement: activity level (resting/low/moderate/high/uncertain), "
    "movement steadiness, and data-quality limits (short track, gaps, jumps).\n"
    "3. If the track is short (<30 observations) or flagged for review, say the observation is "
    "weak and name the limitation first.\n"
    "FORMAT: at most 5 short bullets, under 140 words. "
    "End with: 'Experimental observation only - not validated, not a health assessment.'"
)


def observe_behavior(track):
    """Describe one track's movement via Groq text (primary) then Gemini (fallback).

    track: dict with track_id, observations, duration_sec, mean/median/max speed,
    tracking gaps, review flags. Returns {provider, model, observation, ...}.
    """
    t = track or {}
    user_text = (
        f"track_id={t.get('track_id')} observations={t.get('observations')} "
        f"duration_sec={t.get('duration_sec')} fps={t.get('fps_used')} "
        f"mean_speed_px_sec={t.get('mean_speed_px_sec')} median_speed_px_sec={t.get('median_speed_px_sec')} "
        f"max_valid_speed_px_sec={t.get('max_valid_speed_px_sec')} "
        f"tracking_gaps={t.get('tracking_gaps')} missing_frames={t.get('missing_frames')} "
        f"suspicious_jumps={t.get('suspicious_jumps')} coverage_pct={t.get('coverage_pct')} "
        f"review_tracking={t.get('review_tracking')} review_reasons={t.get('review_reasons')}"
    )[:1500]
    provider, model, text, tried = _run_text(BEHAVIOR_SYSTEM, user_text)
    out = _ok(provider, model, text, tried)
    return _rename_advice(out, "observation")


def _rename_advice(out, key):
    out[key] = out.pop("advice")
    return out


# ---------------------------------------------------------------- structured explanation (§8.2) + cache/cooldown (§8.3)
EXPLANATION_FIELDS = ["summary", "water_quality_explanation", "behavior_observations",
                      "risk_factors", "supporting_evidence", "recommended_checks",
                      "missing_information", "limitations"]
_LIST_FIELDS = {"risk_factors", "supporting_evidence", "recommended_checks",
                "missing_information", "limitations"}

EXPLAIN_SYSTEM = (
    "You are the AquacultureAI explanation component. You receive a validated evidence object "
    "(deterministic risk assessment + measurements) and return a structured explanation. "
    "The deterministic risk status is authoritative: restate it, never change it, never invent "
    "a risk it does not contain. Never diagnose fish disease, never predict mortality, never give "
    "drug/chemical doses, never assign numerical disease probabilities. Use ONLY the evidence "
    "given; name what is missing instead of filling gaps.\n"
    "Return ONLY one valid JSON object with EXACTLY these keys (strings, except the *_factors / "
    "supporting_evidence / recommended_checks / missing_information / limitations keys which are "
    "arrays of short strings, max 5 items each): summary, water_quality_explanation, "
    "behavior_observations, risk_factors, supporting_evidence, recommended_checks, "
    "missing_information, limitations. No other text, no markdown fences."
)


def _validate_explanation(obj, provider, model):
    if not isinstance(obj, dict):
        raise LlmError(provider, model, "Explanation was not a JSON object.")
    missing = [f for f in EXPLANATION_FIELDS if f not in obj]
    if missing:
        raise LlmError(provider, model, f"Explanation missing fields: {', '.join(missing)}.")
    out = {}
    for f in EXPLANATION_FIELDS:
        v = obj[f]
        if f in _LIST_FIELDS:
            if isinstance(v, str):
                v = [v] if v.strip() else []
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise LlmError(provider, model, f"Explanation field '{f}' must be an array of strings.")
            out[f] = [x.strip()[:400] for x in v if x.strip()][:5]
        else:
            if not isinstance(v, str) or not v.strip():
                raise LlmError(provider, model, f"Explanation field '{f}' must be a non-empty string.")
            out[f] = v.strip()[:1500]
    return out


def _extract_json_obj(text, provider, model):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0].strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise LlmError(provider, model, f"No JSON object in model output: {t[:160]}")
    try:
        return json.loads(t[start:end + 1])
    except ValueError as e:
        raise LlmError(provider, model, f"Model output was not valid JSON: {e}")


def explain_structured(evidence):
    """Structured JSON explanation of validated evidence.

    evidence: minimal dict (readings, assessments, quality flags, limits).
    Returns (explanation_dict, provider, model, tried). Raises NoKeysError/LlmError.
    generated_at is always set server-side at the endpoint, not by the model.
    """
    user_text = json.dumps(evidence, ensure_ascii=False)[:6000]
    provider, model, text, tried = _run_text(EXPLAIN_SYSTEM, user_text,
                                            max_tokens=1500, json_mode=True)
    return _validate_explanation(_extract_json_obj(text, provider, model), provider, model), \
        provider, model, tried


def evidence_hash(evidence):
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# File-backed explanation cache: backend/data/explanations.json
# {scope_key: {evidence_hash, response, provider, model, generated_at}}
_cache_lock = threading.Lock()
_inflight = {}  # scope_key -> [threading.Event, result-box]


def _cache_path():
    from pathlib import Path
    base = Path(os.environ.get("AQUA_BACKEND_DATA",
                               Path(__file__).resolve().parents[1] / "backend" / "data"))
    return base / "explanations.json"


def _read_cache():
    try:
        p = _cache_path()
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        pass
    return {}


def _write_cache(data):
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass  # cache is best-effort; generation already succeeded


def cooldown_s():
    try:
        return max(0, int(os.environ.get("EXPLAIN_COOLDOWN_S", "60")))
    except ValueError:
        return 60


def explain_cached(scope_key, evidence):
    """User-triggered explanation with cache reuse, cooldown and dedup.

    Same evidence -> cached response (with generated_at + cached:true).
    Changed evidence within cooldown -> CooldownError(retry_after_s, last cached).
    Concurrent duplicate requests share one generation (inflight dedup).
    Returns (response_dict, cached_bool). response_dict includes provider, model,
    tried, generated_at (server-side), evidence_hash.
    """
    h = evidence_hash(evidence)
    with _cache_lock:
        entry = _read_cache().get(scope_key)
    if entry and entry.get("evidence_hash") == h and entry.get("response"):
        resp = dict(entry["response"])
        resp.update(provider=entry.get("provider"), model=entry.get("model"),
                    tried=[], generated_at=entry.get("generated_at"),
                    evidence_hash=h, cached=True)
        return resp, True

    with _cache_lock:
        if scope_key in _inflight:
            ev, box = _inflight[scope_key]
        else:
            ev, box = threading.Event(), {}
            _inflight[scope_key] = (ev, box)
            ev = None  # we are the generator
    if ev is not None:  # duplicate: wait for the in-flight generation
        ev.wait(timeout=cooldown_s() + _timeout() * 4 + 10)
        if "response" in box:
            resp = dict(box["response"])
            resp["cached"] = True  # shared generation, not a new LLM call
            return resp, True
        # generator failed: fall through and try ourselves (entry may exist)

    try:
        with _cache_lock:
            entry = _read_cache().get(scope_key)
        if entry and entry.get("evidence_hash") != h and entry.get("generated_at"):
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(entry["generated_at"])).total_seconds()
            except ValueError:
                age = cooldown_s() + 1
            wait = cooldown_s() - age
            if wait > 0:
                raise CooldownError(int(wait) + 1, last=entry.get("response"))
        explanation, provider, model, tried = explain_structured(evidence)
        generated_at = datetime.now(timezone.utc).isoformat()
        resp = {**explanation, "provider": provider, "model": model, "tried": tried,
                "generated_at": generated_at, "evidence_hash": h, "cached": False,
                "llm_generated": True,
                "disclaimer": "LLM-generated explanation of the deterministic assessment; "
                              "not an independently validated prediction."}
        with _cache_lock:
            data = _read_cache()
            data[scope_key] = {"evidence_hash": h, "response": resp, "provider": provider,
                               "model": model, "generated_at": generated_at}
            _write_cache(data)
            box["response"] = resp
        return resp, False
    finally:
        with _cache_lock:
            cur = _inflight.get(scope_key)
            if cur is not None and cur[1] is box:
                cur[0].set()
                _inflight.pop(scope_key, None)

"""API-based fish detection: Groq vision (primary) + Gemini vision (fallback).

This module REPLACES the local YOLO weights for detection when
AQUA_VISION_BACKEND=api (the default when an LLM key is configured).
Image in -> fish boxes out. No segmentation masks: API vision models return
boxes only, so downstream metrics use box-area proxies (labeled as such).

Providers (best available vision models, Oct 2026):
- Groq: ``meta-llama/llama-4-scout-17b-16e-instruct`` (natively multimodal),
  via the OpenAI-compatible chat-completions endpoint with image_url.
- Gemini fallback: ``gemini-2.5-flash`` (fast vision default; set
  GEMINI_VISION_MODEL=gemini-3.1-pro-preview for max accuracy at higher latency),
  via generateContent with inlineData.

Zero extra dependencies: stdlib urllib + base64. OpenCV (already a project
dependency) is used only to downscale frames before upload.

Honest limits (surfaced to callers, never hidden):
- Boxes are zero-shot API output: no pixel masks, no tracking, coordinates are
  approximate, and "confidence" values are model-estimated, NOT calibrated
  accuracy. Every result must keep the unvalidated / needs-review labeling.
"""
import base64
import json
import os
import threading
import time

import cv2
import numpy as np

from backend.llm import GROQ_UA, LlmError, NoKeysError, _is_auth_error, _post_json

GROQ_VISION_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_VISION_URL_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

GROQ_VISION_DEFAULT = "meta-llama/llama-4-scout-17b-16e-instruct"
GEMINI_VISION_DEFAULT = "gemini-2.5-flash"
GEMINI_VISION_FALLBACK = "gemini-3.1-pro-preview"

MAX_SIDE_PX = 768  # downscale before upload: bounds latency, cost and payload size

PROMPT = (
    "You are a fish detection model. Detect ALL clearly visible fish in this underwater tank image. "
    "Return ONLY valid JSON with this exact shape and no other text: "
    '{"detections": [{"box_2d": [ymin, xmin, ymax, xmax], "confidence": 0.0-1.0}]} '
    "Coordinates are integers 0-1000 relative to image width/height. "
    "Draw one tight box per whole fish body. Small/blurry but recognisable fish count; "
    "do not box reflections, bubbles, pipes or debris. "
    'If no fish is visible return exactly {"detections": []}.'
)


def _groq_skip_on():
    """AQUA_SKIP_GROQ=1 skips the Groq provider for VISION (default 0 = enabled).

    The account behind this key has no vision-capable model (llama-4-scout ->
    404 model_not_found; /models lists only text/audio models), so every frame
    would pay a doomed round-trip before Gemini. Text tasks ignore this flag and
    use llm.LLM_TEXT_ORDER. Rollback: AQUA_SKIP_GROQ=0 (one env var).
    """
    raw = os.environ.get("AQUA_SKIP_GROQ", "0").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def config():
    groq_key = bool(os.environ.get("GROQ_API_KEY"))
    gemini_key = bool(os.environ.get("GEMINI_API_KEY"))
    groq_model = (os.environ.get("GROQ_VISION_MODEL") or GROQ_VISION_DEFAULT).strip()
    groq_skipped = groq_key and _groq_skip_on()
    gemini_first = (os.environ.get("GEMINI_VISION_MODEL") or GEMINI_VISION_DEFAULT).strip()
    gemini_chain = [m for m in [gemini_first, GEMINI_VISION_FALLBACK] if m]
    gemini_chain = list(dict.fromkeys(gemini_chain))
    try:
        timeout = max(10, int(os.environ.get("VISION_TIMEOUT_S", "60")))
    except ValueError:
        timeout = 60
    return {
        "groq_configured": groq_key,
        "gemini_configured": gemini_key,
        "groq_skipped": groq_skipped,
        "groq_model": groq_model if (groq_key and not groq_skipped) else None,
        "gemini_chain": gemini_chain if gemini_key else [],
        "timeout_s": timeout,
    }


def status():
    c = config()
    order = ([f"groq:{c['groq_model']}"] if c["groq_model"] else [])
    order += [f"gemini:{m}" for m in c["gemini_chain"]]
    now = time.time()
    providers = {}
    for p in ("groq", "gemini"):
        t = _tel_state(p)
        until = _UNHEALTHY.get(p, 0)
        providers[p] = {**t,
                        "down_until": until if until > now else None,
                        "down_in_s": int(until - now) + 1 if until > now else None}
    return {
        "groq_configured": c["groq_configured"],
        "gemini_configured": c["gemini_configured"],
        "groq_skipped": c["groq_skipped"],
        "groq_model": c["groq_model"],
        "gemini_chain": c["gemini_chain"],
        "fallback_order": order,
        "providers": providers,
        "masks": False,
        "note": "API vision returns boxes only (no segmentation masks); scores are model-estimated, not calibrated."
                + (" Groq vision skipped: no vision model on this account." if c["groq_skipped"] else ""),
    }


# ---------------------------------------------------------------- frame prep
def prepare_frame(img):
    """BGR image -> (jpeg_bytes, width, height). Downscales to bound payload."""
    h, w = img.shape[:2]
    scale = min(1.0, MAX_SIDE_PX / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        raise LlmError("vision", "preprocess", "Could not encode frame as JPEG.")
    return bytes(buf), w, h


# ---------------------------------------------------------------- parsing (shared)
def _extract_json(text):
    """Pull the first {...} object out of possibly chatty model output."""
    t = (text or "").strip()
    for fence in ("```json", "```"):
        if fence in t:
            t = t.split(fence, 1)[1].rsplit("```", 1)[0] if "```" in t.split(fence, 1)[1] else t.split(fence, 1)[1]
            t = t.strip()
            break
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise LlmError("vision", "parse", f"No JSON object in model output: {t[:160]}")
    try:
        return json.loads(t[start:end + 1])
    except ValueError as e:
        raise LlmError("vision", "parse", f"Model output was not valid JSON: {e}")


def _normalise_boxes(obj, provider, model):
    """box_2d [ymin,xmin,ymax,xmax] 0-1000 -> box [x1,y1,x2,y2] 0-1. Drops invalid entries."""
    dets = obj.get("detections") if isinstance(obj, dict) else None
    if not isinstance(dets, list):
        raise LlmError(provider, model, "Model JSON has no 'detections' list.")
    out = []
    for d in dets[:200]:
        if not isinstance(d, dict):
            continue
        b = d.get("box_2d") or d.get("box") or d.get("bbox")
        if not isinstance(b, (list, tuple)) or len(b) != 4:
            continue
        try:
            ymin, xmin, ymax, xmax = (float(v) / 1000.0 for v in b)
        except (TypeError, ValueError):
            continue
        x1, y1, x2, y2 = min(xmin, xmax), min(ymin, ymax), max(xmin, xmax), max(ymin, ymax)
        x1, y1 = max(0.0, x1), max(0.0, y1)
        x2, y2 = min(1.0, x2), min(1.0, y2)
        if x2 - x1 < 0.005 or y2 - y1 < 0.005 or (x2 - x1) * (y2 - y1) > 0.9:
            continue  # sliver or whole-frame box: not a fish
        try:
            conf = float(d.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        out.append({"box": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                    "confidence": round(min(1.0, max(0.0, conf)), 3)})
    return out


# ---------------------------------------------------------------- providers
def _call_groq_vision(model, jpeg_bytes, api_key, timeout):
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    _, body = _post_json(
        GROQ_VISION_URL,
        {"model": model, "temperature": 0.1, "max_tokens": 2000,
         "messages": [{"role": "user", "content": [
             {"type": "text", "text": PROMPT},
             {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]},
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": GROQ_UA},
        timeout=timeout,
    )
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LlmError("groq", model, "Unexpected Groq vision response shape.")
    return _normalise_boxes(_extract_json(text if isinstance(text, str) else ""), "groq", model)


def _call_gemini_vision(model, jpeg_bytes, api_key, timeout):
    import urllib.parse
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    url = GEMINI_VISION_URL_TMPL.format(model=model) + "?key=" + urllib.parse.quote(api_key, safe="")
    _, body = _post_json(
        url,
        {"contents": [{"role": "user", "parts": [
            {"text": PROMPT},
            {"inlineData": {"mimeType": "image/jpeg", "data": b64}}]}],
         "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2000}},
        timeout=timeout,
    )
    try:
        parts = body["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except (KeyError, IndexError, TypeError):
        err = (body.get("error") or {}).get("message", "") if isinstance(body, dict) else ""
        raise LlmError("gemini", model, f"Unexpected Gemini vision response. {err}"[:300])
    return _normalise_boxes(_extract_json(text), "gemini", model)


# ---------------------------------------------------------------- entry point
# Provider health: a provider that fails with an auth error (bad/blocked key)
# or quota exhaustion (429) is skipped until its cooldown expires, so a dead
# provider is not retried on every frame and an exhausted quota is not hammered.
# Cooldowns are env-tunable; state is process-local and key-free.
_UNHEALTHY = {}  # provider -> epoch seconds when it may be retried
_UNHEALTHY_LOCK = threading.Lock()

# Per-provider telemetry (B3): calls, fails, last HTTP status, last error, last
# parsed retry-after. Process-local, key-free, exposed via /api/vision-status.
_TELEMETRY = {}
_BLANK_TEL = {"calls": 0, "fails": 0, "last_status": None, "last_error": None, "last_retry_after_s": None}


def _tel_state(provider):
    with _UNHEALTHY_LOCK:
        return dict(_TELEMETRY.get(provider, _BLANK_TEL))


def _tel_call(provider):
    with _UNHEALTHY_LOCK:
        t = _TELEMETRY.setdefault(provider, dict(_BLANK_TEL))
        t["calls"] += 1


def _tel_ok(provider, status=200):
    with _UNHEALTHY_LOCK:
        t = _TELEMETRY.setdefault(provider, dict(_BLANK_TEL))
        t["last_status"] = status
        t["last_error"] = None


def _tel_fail(provider, err):
    with _UNHEALTHY_LOCK:
        t = _TELEMETRY.setdefault(provider, dict(_BLANK_TEL))
        t["fails"] += 1
        t["last_status"] = getattr(err, "status_code", None)
        t["last_error"] = (getattr(err, "message", None) or str(err))[:200]
        t["last_retry_after_s"] = getattr(err, "retry_after", None)


def _cooldown(env_name, default_s):
    try:
        return max(30, int(os.environ.get(env_name, str(default_s))))
    except ValueError:
        return default_s


def _skip_provider(provider):
    """(skip, retry_in_s): True while the provider is in cooldown."""
    with _UNHEALTHY_LOCK:
        until = _UNHEALTHY.get(provider, 0)
        remaining = until - time.time()
        if remaining > 0:
            return True, int(remaining)
        _UNHEALTHY.pop(provider, None)
        return False, 0


def _mark_down(provider, retry_after_s):
    with _UNHEALTHY_LOCK:
        _UNHEALTHY[provider] = time.time() + retry_after_s


def _is_quota_error(message):
    return "http 429" in (message or "").lower()


def detect_image(img_or_jpeg, jpeg_bytes=None):
    """Detect fish in one frame. Accepts a BGR array or pre-encoded JPEG bytes.

    Returns {"detections", "provider", "model", "fallback_used", "tried"}.
    Raises NoKeysError / LlmError (key-free messages).
    """
    if jpeg_bytes is None:
        if isinstance(img_or_jpeg, (bytes, bytearray)):
            jpeg_bytes = bytes(img_or_jpeg)
        else:
            jpeg_bytes, _, _ = prepare_frame(img_or_jpeg)
    cfg = config()
    groq_key = os.environ.get("GROQ_API_KEY") or ""
    gemini_key = os.environ.get("GEMINI_API_KEY") or ""
    timeout = cfg["timeout_s"]
    auth_cd = _cooldown("VISION_AUTH_COOLDOWN_S", 300)
    quota_cd = _cooldown("VISION_QUOTA_COOLDOWN_S", 120)
    tried, failures = [], []
    hints = []

    if cfg["groq_model"]:
        skip, wait = _skip_provider("groq")
        if skip:
            tried.append("groq:skipped")
            failures.append(f"groq skipped (cooldown, retry in ~{wait}s)")
        else:
            _tel_call("groq")
            try:
                dets = _call_groq_vision(cfg["groq_model"], jpeg_bytes, groq_key, timeout)
                _tel_ok("groq")
                return {"detections": dets, "provider": "groq", "model": cfg["groq_model"],
                        "fallback_used": False, "tried": tried}
            except LlmError as e:
                _tel_fail("groq", e)
                tried.append(f"groq:{cfg['groq_model']}")
                failures.append(f"groq:{cfg['groq_model']} -> {e.message}"[:200])
                if _is_auth_error(e.message):
                    _mark_down("groq", auth_cd)
                    hints.append("Groq key was rejected (HTTP 401/403): regenerate it at console.groq.com, "
                                 "or leave it — Gemini is used meanwhile.")
                elif _is_quota_error(e.message):
                    _mark_down("groq", max(quota_cd, int(getattr(e, "retry_after", None) or 0)))
    elif cfg["groq_skipped"]:
        tried.append("groq:skipped(skip-flag)")
        failures.append("groq skipped (AQUA_SKIP_GROQ=1: no vision model on this Groq account)")

    for model in cfg["gemini_chain"]:
        skip, wait = _skip_provider("gemini")
        if skip:
            tried.append("gemini:skipped")
            failures.append(f"gemini skipped (cooldown, retry in ~{wait}s)")
            break
        _tel_call("gemini")
        try:
            dets = _call_gemini_vision(model, jpeg_bytes, gemini_key, timeout)
            _tel_ok("gemini")
            return {"detections": dets, "provider": "gemini", "model": model,
                    "fallback_used": len(tried) > 0, "tried": tried}
        except LlmError as e:
            _tel_fail("gemini", e)
            tried.append(f"gemini:{model}")
            failures.append(f"gemini:{model} -> {e.message}"[:200])
            if _is_auth_error(e.message):
                _mark_down("gemini", auth_cd)
                hints.append("Gemini key was rejected (HTTP 401/403): check the key in Google AI Studio.")
                break  # same key for the whole chain
            if _is_quota_error(e.message):
                _mark_down("gemini", max(quota_cd, int(getattr(e, "retry_after", None) or 0)))
                hints.append("Gemini quota exhausted (HTTP 429): lower the live-analysis rate "
                             "(VITE_LIVE_ANALYZE_MS) or check plan/billing. Automatic retry after cooldown.")

    if not tried:
        raise NoKeysError()
    msg = "All vision attempts failed: " + " | ".join(failures)[:600]
    if hints:
        msg += " Hint: " + " ".join(dict.fromkeys(hints))[:300]
    raise LlmError("all", "all", msg)


def draw_boxes(img, detections, color=(255, 0, 0)):
    """Draw API boxes + estimated scores on a BGR image (for the preview frame)."""
    h, w = img.shape[:2]
    out = img.copy()
    for d in detections:
        x1, y1, x2, y2 = d["box"]
        p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
        cv2.rectangle(out, p1, p2, color, 2)
        cv2.putText(out, f"fish {d['confidence']:.2f} (est.)", (p1[0], max(0, p1[1] - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return out

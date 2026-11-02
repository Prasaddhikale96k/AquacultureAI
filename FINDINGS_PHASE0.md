# FINDINGS_PHASE0 — Investigation only, no code changed

## Environment (verbatim)
- GPU: NVIDIA GeForce RTX 3050 6GB Laptop GPU, total 6144 MiB, free 6001 MiB
- Python: 3.13.2 | Node: v24.12.0
- starlette 1.6.0 | ultralytics 8.4.178 | transformers 5.5.3 | opencv-python 5.0.0.93
- `.env` present at project root. `AQUA_VISION_BACKEND=yolo` (`.env:29`). Groq + Gemini keys present in `.env` (`.env:12-13`), process env wins over `.env` (`backend/env.py:46`).

## Diagnosis verdicts (`scripts/diagnose_vision_keys.py`)
```
env file present=True (process env wins over .env)
GROQ_API_KEY      : gsk_...uo1t
GEMINI_API_KEY    : AQ.A...Cu3Q
GROQ_VISION_MODEL : meta-llama/llama-4-scout-17b-16e-instruct
GROQ_MODEL        : openai/gpt-oss-120b
GEMINI_VISION_MODEL: gemini-2.5-flash
GEMINI_MODEL      : gemini-3.1-pro-preview

=== groq vision ===
status=403 latency_ms=517 verdict=KEY_INVALID
headers={}
error=error code: 1010
VERDICT: KEY_INVALID

=== groq text ===
status=403 latency_ms=204 verdict=KEY_INVALID
headers={}
error=error code: 1010
VERDICT: KEY_INVALID

=== gemini vision ===
status=200 latency_ms=2433 verdict=OK
headers={}
error=
VERDICT: OK

=== gemini text ===
status=429 latency_ms=865 verdict=QUOTA_EXHAUSTED
headers={}
error={"error":{"code":429,"message":"You exceeded your current quota..."}}
VERDICT: QUOTA_EXHAUSTED
```
- Groq key is **invalid** (403 / error code 1010) for both vision and text.
- Gemini **vision works** (200 OK, latency 2433 ms).
- Gemini **text quota exhausted** (429).

## Live backend capture (`python -m uvicorn backend.main:app --port 8000`, then stopped)
```
GET /health  -> 200
{"status":"ok","model_available":true,"model_validated":false,
 "vision_backend":"yolo",
 "llm":{"groq_configured":true,"gemini_configured":true}}

GET /api/vision-status -> 200
{"groq_configured":true,"gemini_configured":true,
 "groq_model":"meta-llama/llama-4-scout-17b-16e-instruct",
 "gemini_chain":["gemini-2.5-flash","gemini-3.1-pro-preview"],
 "backend":"yolo", ...}
```
`vision_backend` reads `"yolo"` **only because `.env:29` explicitly sets `AQUA_VISION_BACKEND=yolo`** (takes priority at `main.py:65-67`).

## Code-grounded answer

**When keys exist and AQUA_VISION_BACKEND is unset, the LIVE path calls the cloud API, not local YOLO.**

Proof:
- `main.py:50-73` `vision_backend()`: explicit env wins; otherwise, if `api_vision.status()` reports any LLM key configured → returns `"api"`; only if no key is configured does it fall to `"yolo"` (`main.py:71-73`). So with keys present and env unset → `"api"`.
- `main.py:500-508` `_detect_frame(img, vb)`: calls `_live_predict_api(img)` (cloud) when `vb == "api"`, otherwise `_live_predict(img)` (local YOLO at `main.py:469`).
- `main.py:549-556` `_live_predict_api`: delegates to `api_vision.detect_image(img)`.
- `vision.py:227-294` `detect_image`: Groq vision first, Gemini vision second; both are cloud calls. No YOLO anywhere in this path.

**What happens when the cloud returns 429/404 mid-session — no silent YOLO fallback.**

Proof:
- `vision.py:227-294`: on 429, the provider is marked down with a cooldown (`vision.py:264-287`) and the next provider in the chain is tried; on 404/model-not-found the `LlmError` propagates and the next provider is tried (`vision.py:277`). If all attempts fail, `detect_image` raises `LlmError("all", "all", ...)` (`vision.py:294`) — **it never calls local YOLO**.
- `main.py:537-540` (`live_detect`) and `main.py:591-598` (`live_track`): `_detect_frame` is wrapped in `try/except Exception` that returns a **500** JSON error (`main.py:539-540`, `597-598`). The cloud error surfaces as a 500 to the frontend; there is no branch that retries with `_live_predict` (YOLO).

So: unset + keys → cloud API for live frames; cloud 429/404 → next cloud provider, then a 500 error to the client — **never a silent fallback to local YOLO**.

## Cadence as coded (live analyze)
`frontend/src/hooks/useLiveCamera.ts:10`: `ANALYZE_EVERY_MS = Math.max(3000, VITE_LIVE_ANALYZE_MS ?? 10000)` → default **10000 ms** between analysis requests (preview tick 1000 ms, line 6); quota pause 60000 ms on 429 (`useLiveCamera.ts:11, 181-184`).

## Conclusion (no fix yet)
The live path is API-first by configuration, not YOLO. The currently-active `.env` forces `yolo` via `AQUA_VISION_BACKEND=yolo`, so right now live uses local weights. Groq key is invalid; Gemini vision works but Gemini text is quota-exhausted. No silent cloud→YOLO fallback exists in code; cloud failures surface as 500.

STOP — awaiting next instruction before any fix.

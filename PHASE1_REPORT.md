# PHASE 1 REPORT — LS (Local Showdown): honest live pipeline, revived text LLM

Date: 2026-10-17 · Scope: F (config) → A (processed input) → B (truth in UI) → C (detection hygiene) → D (frame capture) → E (hygiene)
Status: **complete** — `pytest tests/ -q` → 134 passed; `frontend npm run build` → clean (tsc + vite).
Git: **this project is not a git repository** (`Test-Path .git` = False), so no commit was possible. Suggested message when git is initialized: `phase-1: Groq UA fix, degraded live honesty, processed input, captures`.

---

## PART 1 — What changed (developer changelog)

### F1 — Gemini text model + text-provider order (config only)
- `.env:19-20` `GEMINI_MODEL=gemini-2.5-flash` (old `gemini-3.1-pro-preview` line commented; it 429s on this plan).
- `.env:47` `LLM_TEXT_ORDER=groq,gemini` (Groq text is alive again after F2; Gemini text free tier is exhausted today).
- Read by `backend/llm.py:87` (`LLM_TEXT_ORDER`) and `backend/llm.py:107` (`GEMINI_MODEL`) — keys matched, no code change needed.

### F2 — Groq 403/1010 (Cloudflare) fixed with a shared User-Agent
- `backend/llm.py:55` `GROQ_UA = "AquacultureAI/1.0"` — default python-urllib UA gets HTTP 403 `error code: 1010`; custom UA passes (measured in Phase 0).
- `backend/llm.py:202` Groq text header `User-Agent: GROQ_UA`.
- `backend/vision.py:185` Groq vision header `User-Agent: GROQ_UA` (imported at `backend/vision.py:31`).
- `backend/llm.py:183` `LlmError.status_code` + `retry_after` attached in `_post_json`; `backend/llm.py:144` `_retry_after_s()` parses `Retry-After`/`x-ratelimit-reset-*` for cooldown + telemetry.

### F2b — Groq vision has no model on this account → vision-only skip flag
- `backend/vision.py:54` `_groq_skip_on()` (`AQUA_SKIP_GROQ`, default **0** in code for test hermeticity) and `backend/vision.py:326-327` skip trace `groq:skipped(skip-flag)`.
- `.env:55` `AQUA_SKIP_GROQ=1` (text tasks ignore it and use `LLM_TEXT_ORDER`).
- Default `AQUA_SKIP_GROQ` in code stays 0 so tests are hermetic; only `.env` opts in.

### F3 — untouched (honoured)
- `AQUA_VISION_BACKEND=yolo` in `.env` left exactly as the owner set it.

### A — Processed input: rotate/crop applied in the browser, before send AND in preview
- `frontend/src/hooks/useLiveCamera.ts:40` `CROP_PRESETS` (none / trim top 12% / trim top 20%), `:48` `normalizeCrop` (validates `x1,y1,x2,y2`, 0–1, ≥5% size), `:64` `cropPresetId`.
- `:71` `drawProcessed()` — rotate (0/90/180/270) then crop, scaled to `MAX_WIDTH`, into any destination canvas.
- `:123`/`:129` `setRotate`/`setCrop` — persisted in `localStorage` (`aqua.live.rotate`, `aqua.live.crop`); invalid crop returns `false` and keeps the old value.
- `:241` the analysis frame (`sendOne`) and the preview loop (rAF, `:285-297`) both use `drawProcessed` → **what the model sees is what the user sees**; overlay boxes align by construction.
- `frontend/src/sections/FishMonitoring.tsx:76-78` — visible preview is now a `<canvas>` (video element hidden 1px), overlay canvas unchanged on top.
- `:98`/`:116` rotate + crop controls under the camera buttons (custom box with Apply + inline validation message).

### B — The UI tells the truth; cloud failures degrade instead of 500
- `backend/main.py:519` `live_fallback_on()` (`AQUA_LIVE_ALLOW_FALLBACK`, default 0).
- `backend/main.py:530` `_degraded_frame_result()` — returns HTTP 200, `detections: []`, `visionBackend: "api"`, `degraded: true`, `degradedReason: <first 300 chars, paths stripped>`; with the fallback flag it runs local YOLO once and labels `visionBackend: "yolo-fallback(api-down)"`.
- `backend/main.py:632-641` (`/api/live/detect`) and `:693-710` (`/api/live/track`) catch `llm.LlmError` on the api backend only; every response now carries `visionBackend`/`degraded`/`degradedReason`.
- `backend/vision.py:88-112` `/api/vision-status` now reports `groq_skipped` + per-provider telemetry (`calls`, `fails`, `last_status`, `last_error`, `last_retry_after_s`, `down_until`, `down_in_s`) — populated by `:235`/`:248`.
- `frontend/src/sections/FishMonitoring.tsx:42-50` truth badge: green `LIVE: local YOLO · N fish` / blue `LIVE: API vision · N fish` / amber `API DOWN — <reason>[ · local YOLO fallback]` / red `LIVE: API vision · no detections`.
- `frontend/src/types/index.ts` — `LiveResult.visionBackend/degraded/degradedReason`, `LiveTrack.confirmed/box`, `VisionStatus.groq_skipped/providers`.

### C — Detection hygiene on pure frames
- `backend/main.py:250-254` `live_conf()` now `max(AQUA_CONF, AQUA_LIVE_CONF_MIN=0.35)` — live-path floor only; recorded-video confidence untouched. Rollback: `AQUA_LIVE_CONF_MIN=0`.
- `backend/live_track.py:42-43` `CONFIRM_WINDOW=5`, `CONFIRM_MIN_HITS=3`; hit/miss window per track (`:189-201`); payload now includes `confirmed` and last `box` (`:216-217`).
- `frontend/src/hooks/useLiveCamera.ts:304-331` — unconfirmed tracks render dashed + faded (matched to detections by box center); `FishMonitoring.tsx` tracking tile shows `confirmed/total (dashed = tentative)`.

### D — Frame capture for offline evaluation
- `backend/main.py:549-574` `dataset/live_captures/<YYYY-MM-DD>/<HHMMSS-mmm>.{jpg,json}`, one pair per session per `AQUA_LIVE_CAPTURE_EVERY_S` (30 s), cap `AQUA_LIVE_CAPTURE_MAX` (2000 pairs, oldest pruned), lock-guarded, failures never affect the response. JSON carries detections, tracks, movement, backend and degraded state.
- Captures the **processed** body (what was analysed), saved after tracking (`main.py:710`).
- `.gitignore` — `dataset/live_captures/` added (generated data, not source).

### E — Hygiene
- `.gitignore` — `.env.local`, `**/.env.local`, `frontend/.env.local` added.
- Test hermeticity: `AQUA_SKIP_GROQ`, `AQUA_LIVE_ALLOW_FALLBACK` added to env-clearing lists (`tests/test_live_detect.py:27-28`, `tests/test_backend_api.py:29-30`, `tests/test_vision_backend.py:34-38`); live-track route tests force `AQUA_LIVE_CAPTURE=0` (`tests/test_live_track.py:204-210`, `:251-258`) so test runs never write captures.
- Tests were failing before this fix because `backend.main` loads the real `.env` at import — the new flags leaked into the test process. Fixed, 134/134 green.

### Tests added (6 new; 128 → 134)
- `tests/test_vision_backend.py:107` degraded 200 (no 500) with telemetry path; `:124` fallback flag runs labelled YOLO; `:188` skip flag bypasses Groq and reports telemetry.
- `tests/test_live_track.py:180` confirm after 3 hits + box; `:189` misses unconfirm but keep the track; `:261` route-level degraded 200 keeps the session alive.

### Evidence (live verification, 2026-10-17)
| Check | Result |
| --- | --- |
| `POST /api/explanation {"tankId":"01"}` | **200 · provider=groq · model=openai/gpt-oss-120b · tried=[]** (Groq UA fix works in production path) |
| `POST /api/live/detect` with `AQUA_VISION_BACKEND=api` (port 8001) | **200 · degraded=True** · reason: `All vision attempts failed: groq skipped (AQUA_SKIP_GROQ=1: no vision model…) | gemini:gemini-2.5-flash -> HTTP 429 quota` — the degraded path proven end-to-end live |
| `/api/vision-status` (api process) | `groq_skipped=true` · telemetry `gemini: calls=1, fails=1, last_status=429`, cooldown reported |
| `POST /api/live/track` (yolo, port 8000) | 200 · `visionBackend=yolo` · 7 detections, 7 tracks with `box`+`confirmed` |
| Capture (D) | pair written `dataset/live_captures/2026-10-17/073558-148.jpg/.json` — jpg = exact 97 365 bytes sent; json `session=phase1verify, visionBackend=yolo, 7 detections, 7 tracks`. Deleted after verification (test-video frame, not real camera data). |

---

## PART 2 — HOW TO VERIFY (no coding needed)

1. **Start the system**
   - Backend: open a terminal in the project folder and run `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`.
   - Frontend: in `frontend/` run `npm run dev`, then open http://localhost:5173 → **Fish Monitoring**.

2. **Live camera badge tells the truth**
   - With today's `.env` (`AQUA_VISION_BACKEND=yolo`) the badge under the panel title reads green **“LIVE: local YOLO · N fish”** — detections come from the local weights, nothing is sent to the cloud.
   - If you switch the backend to cloud vision (set `AQUA_VISION_BACKEND=api` in `.env`, restart the backend) and the cloud fails, you will see an amber **“API DOWN — <reason>”** badge and the live stream keeps running (no more error screen). When the cloud works you get a blue **“LIVE: API vision · N fish”**. A red badge means “API vision · no detections”.

3. **Rotate / crop (the “poisoned frame” fix)**
   - With the camera on, use **Rotate** (0°/90°/180°/270°) and **Crop** (Full frame / Trim top 12% / Trim top 20% / Custom…) under the preview.
   - The preview, the boxes and the frames sent to the model all change together — verify by rotating 90°: fish should stay boxed exactly where you see them. Your choice is remembered after reload. “Custom…” accepts `x1,y1,x2,y2` between 0 and 1; wrong input shows a red hint and keeps the old crop.

4. **Prove the text LLM is alive again (Groq)**
   - In PowerShell: `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/explanation -ContentType application/json -Body '{"tankId":"01"}'` — the reply should say `"provider": "groq"` and `"llm_generated": true`. (Gemini text is out of free daily quota today; it will be tried again automatically after the daily reset.)

5. **Frame collection for offline testing (D)**
   - Leave the camera running for a few minutes, then look in `dataset/live_captures/<today's date>/`: one `.jpg` + `.json` pair every ~30 s per session. The JSON records what was detected and which backend produced it.
   - To turn collection off: add `AQUA_LIVE_CAPTURE=0` to `.env` and restart the backend. Oldest frames are pruned automatically beyond 2 000 pairs.

6. **Rollback (one env var each, no code edits)**
   | Want | Set |
   | --- | --- |
   | Old live detection floor | `AQUA_LIVE_CONF_MIN=0` |
   | Never run local YOLO when API is down | (default) `AQUA_LIVE_ALLOW_FALLBACK=0`; set `=1` to enable labelled fallback |
   | Stop saving frames | `AQUA_LIVE_CAPTURE=0` |
   | Stop skipping Groq vision | `AQUA_SKIP_GROQ=0` (do this after adding a vision model via `GROQ_VISION_MODEL`) |
   | Old text order | `LLM_TEXT_ORDER=gemini,groq` |
   | Reset rotate/crop | set both back in the UI, or clear browser localStorage keys `aqua.live.rotate` / `aqua.live.crop` |

7. **Things only you can do (operator actions)**
   - **Groq vision:** this Groq account has no vision-capable model. When one is available, set `GROQ_VISION_MODEL` in `.env` and `AQUA_SKIP_GROQ=0`, restart — frames then try Groq first again.
   - **Gemini quotas:** the free daily quota for `gemini-2.5-flash` was exhausted both for text and vision today (HTTP 429 on both). It resets daily; if the camera must run cloud-side all day, consider enabling billing on the Google AI Studio project.
   - **Git:** initialise the repository when ready (`git init`, first commit), then commit this phase.

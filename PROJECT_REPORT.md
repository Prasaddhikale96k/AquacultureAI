# PROJECT_REPORT.md — AquacultureAI Full Deep-Dive (DEBUG + CODE REVIEW)

> Generated: 2026-10-16 by repo scan (root `C:\Users\vitho\AquacultureAI`). Language: English (technical terms English). Secrets REDACTED. Har claim ke saath `file:line` + snippet proof hai. Code jaisa HAI waisa likha hai.

---

## 0. EXECUTIVE SNAPSHOT

**Project naam:** AquacultureAI
**Ek line mein:** Tilapia RAS (Recirculating Aquaculture System) ke liye fish-video monitoring + rule-based water-quality screening + LLM explanation dashboard.
**Real-world problem:** Fish farmer ko pata chale — paani kharab hai kya (temperature/pH/DO/turbidity/ammonia), camera mein fish dikh rahe hain kya, movement normal hai kya — bina manual lab round ke, provisional screening ke saath, over-claim kiye bina.

**Tech stack:**

| Layer | Technology | Version (jahan confirm hua) | Kis file/folder mein use |
|---|---|---|---|
| Backend API | Starlette (not FastAPI) + uvicorn | ❓VERIFY NEEDED — no `requirements.txt`; `backend/main.py:21-27` imports starlette | `backend/main.py:1-1050` |
| Vision (recorded) | Ultralytics YOLO-seg `tilapia_seg best.pt` | Ultralytics (version ❓VERIFY NEEDED) | `school_movement_metrics.py:18,95`, `backend/main.py:962` |
| Vision (API mode) | Groq vision `meta-llama/llama-4-scout-17b-16e-instruct` + Gemini `gemini-2.5-flash` fallback | Oct-2026 defaults in code | `backend/vision.py:37-39`, `backend/api_analysis.py:1-111` |
| Live detect | YOLO + adaptive tiled escalation + Canny edge gate | — | `backend/live_detect/predict_tiled.py:1-151`, `backend/main.py:250-516` |
| Live track | Greedy centroid tracker, phase-correlation camera gate, motion gate | — | `backend/live_track.py:1-251` |
| Water engine | Pure Python rule engine (no ML) | — | `backend/water.py:1-493`, `backend/water_rules.json:1-131` |
| Risk engine | Deterministic 5-level mapper | `risk/v1` string in code | `backend/risk.py:1-137` |
| LLM layer | stdlib `urllib` → Groq OpenAI-compat + Gemini `generateContent` | No SDK | `backend/llm.py:1-545` |
| Frontend | React 19.3.1 + Vite 8.3.4 + Tailwind 4.3.3 + Recharts 3.10.1 + framer-motion 14.2.0 | `frontend/package.json:11-26` | `frontend/src/*` (36 ts/tsx, ~3000 LOC) |
| Legacy dashboard | Streamlit | ❓VERIFY NEEDED version | `app.py:1-202` |
| Data scripts | pandas, numpy, scikit-learn, joblib, matplotlib, opencv | ❓VERIFY NEEDED versions (no lock) | `water_quality_model.py`, `train_behavior_*.py`, `extract_*.py` |
| Storage | JSONL files + CSVs, no RDBMS | — | `backend/water.py:157-184`, `backend/history.py:19-43`, `backend/data/jobs/<id>/` |
| IoT cloud | ThingSpeak `feeds.json` read-only (ESP32 → ThingSpeak → dashboard) | API `api.thingspeak.com` | `frontend/src/services/thingspeak.ts:97-110`, `SENSORS.md:1-27` |
| Tests | pytest (12 files) | ❓VERIFY NEEDED runner config | `tests/test_*.py` |

**Current state (honest %):**

- ~70% complete as research prototype, ~35% as production system.
- **Chalta hai:** backend health/upload/analyse/results/frames/live-detect/live-track/water-CRUD/risk/explanation/history (`backend/main.py:1029-1050` routes); ThingSpeak polling + stale/no-data states (`frontend/src/hooks/useSensors.ts:8-59`); water rule engine + 5-level risk + validation tests; YOLO local detection measured F1 0.9577 (`eval_detection.json` local block, `VALIDATION.md:14-16`); zebrafish RF baseline with grouped CV (`runs/behavior_baseline/metrics.json`).
- **Toota / Blocked hai:** API-vision arm BLOCKED without keys at eval time (`eval_detection.json: api.status=BLOCKED`); tilapia behavior classifier invalid — provisional labels only, centroid refuses prediction by design (`behavior_live.py:131-142`); no DB/migrations/backup/monitoring/CI; no `requirements.txt`; frontend `dist/` committed but stale risk; live API path unevaluated on tilapia (`backend/main.py:59-63` comment).
- **TL;DR (5 lines):** 1) Ye tilapia tank screening tool hai, disease diagnosis nahi. 2) Paani ke rules provisional JSON mein hain, ML nahi. 3) Fish detection YOLO-seg se validated (F1 0.9577, 1 session), API vision zero-shot unevaluated. 4) Live sensors sirf ThingSpeak se (Temp + raw turbidity ADC), pH/DO unmapped inactive. 5) Sabse pehle fix: secrets hygiene + turbidity NTU misread rokna + API-first override ka eval + backend rate-limit/auth.

**GAPS / JO MUJHE NAHI MILA (Sec 0):** `requirements.txt`/`pyproject.toml` nahi mila — backend dep versions unverified. Python version, OS target, Docker/CI config nahi mila. Live ThingSpeak channel ID/values REDACTED hone se actual freshness/volume verify nahi hua.

---

## 1. FULL REPO MAP

### 1.1 Directory tree (junk skipped: `node_modules/.git/.venv/__pycache__/.pytest_cache/runs/weights/test_videos/track_review_frames/behavior_review_frames`)

```
AquacultureAI/
  app.py (202 lines, Streamlit legacy dashboard)
  app_backup_before_behavior_integration.py
  backend/
    main.py (1050 lines, Starlette API — entry point)
    water.py (493, rule engine + storage + 4 routes)
    llm.py (545, Gemini/Groq text + explanation cache)
    vision.py (307, Groq/Gemini vision detection)
    api_analysis.py (111, sampled API video analysis)
    live_track.py (251, session tracker)
    live_detect/__init__.py (5) + predict_tiled.py (151)
    risk.py (137), history.py (69), env.py (49)
    water_rules.json (131), data/jobs/<id>/ (runtime)
  frontend/
    src/App.tsx (66), main.tsx (6)
    components/ Background,Header,Shell,Toasts,ui
    hooks/ useSensors(60), useBackendState(22), useLiveCamera(230), useAnalysis(119)
    services/ thingspeak(118), api(166), historical(225), video(36), demo(8)
    sections/ LiveSensors(156), StatusPanels(85), WaterAssessment(81), WaterForm(146),
              AssessmentReport, AiAdvisor, RiskPanel, BehaviorPanel, FishMonitoring(135),
              VideoAnalysis, UploadPanel, ResultsPanel, HistoryPanel, Observations, etc.
    config/alerts.ts (81), types/index.ts (194)
    package.json, vite.config.ts, tsconfig.json, .env.example, .env.local (REDACTED values)
  tests/ (12 files, ~1900 lines total)
  *.py root scripts: school_movement_metrics(188), behavior_live(142), behavior_model(75),
    train_behavior_model(83), train_behavior_baseline(185), extract_behavior_features(106),
    extract_fish_features, extract_bytetrack_features, clean_and_summarize_track,
    evaluate_detection(199), water_quality_model(96), water_quality_dashboard(25), etc.
  dataset/ tilapia_yolo (7669 train + 6604 test boxes + val), zebrafish_behavior_prepared/,
           Tilapia RAS Dataset/, Tilapia RAS Dataset-1.zip
  runs/behavior_baseline/ (metrics.json, confusion_matrix_*, fold_assignments, RF joblib)
  behavior_random_forest.joblib (legacy tilapia provisional model)
  *.csv (water_quality_analysis, fish_track_quality_summary*, school_movement_*, behavior_*)
  *.json (eval_detection.json, eval_detection_pilot.json, water_quality_config.json, dataset_inventory.csv)
  SENSORS.md, VALIDATION.md, backend_uvicorn.log, backend_uvicorn_err.log
  backups_dashboard_fix/, backups_school_movement/ (stale copies)
  .env (REDACTED, 12 vars), .env.example, .gitignore, skills-lock.json
```

Har top-level folder 1-2 lines:

- `backend/` — Starlette API + deterministic engines + LLM/vision adapters. Yehi production server hai.
- `frontend/` — React+Vite dashboard (2 pages: dashboard + monitoring). ThingSpeak polling + video upload/live camera yahin.
- `tests/` — pytest unit/integration (mocked; live integration Blocked).
- `dataset/` — YOLO-seg labels/images + zebrafish keypoints + Tilapia RAS CSVs. Sabse bada, git mein heavy.
- `runs/`, `weights/`, `*.joblib/*.pt` — trained artifacts (YOLO best.pt, RF baselines).
- `backups_*/`, `app_backup_*` — stale copies, dead code source.
- `track_review_frames/`, `behavior_review_frames/`, `test_videos/` — manual review media (scan se excluded, heavy).

### 1.2 Files table (critical only; full LOC `python -c` output se)

| File path | LOC | Kaam | Critical |
|---|---|---|---|
| `backend/main.py` | 1050 | All HTTP routes, upload/analyse/live/sanitize/worker | High |
| `backend/llm.py` | 545 | Text LLM fallback, prompt guardrails, explanation cache/cooldown | High |
| `backend/water.py` | 493 | Validation, unit conversion, rule eval, JSONL store, combine | High |
| `backend/vision.py` | 307 | API vision detect (Groq→Gemini), cooldowns, box normalise | High |
| `backend/live_track.py` | 251 | Session greedy tracker, camera/motion gates | High |
| `school_movement_metrics.py` | 188 | Recorded-video YOLO pipeline (process+summarize) | High |
| `train_behavior_baseline.py` | 185 | Zebrafish grouped-CV baseline (correct discipline) | High |
| `frontend/src/types/index.ts` | 194 | All TS contracts (Risk/Water/Live/Explanation) | High |
| `frontend/src/services/api.ts` | 166 | Backend client, upload XHR, risk/explain wrappers | High |
| `frontend/src/sections/LiveSensors.tsx` | 156 | Metric/History cards, recharts AreaChart | Med |
| `backend/live_detect/predict_tiled.py` | 151 | Adaptive single→tiled detection, NMS | High |
| `frontend/src/sections/WaterForm.tsx` | 146 | Water input form | Med |
| `behavior_live.py` | 142 | Centroid buffer + refuse-to-predict guard | High |
| `backend/risk.py` | 137 | 5-level risk mapping, confirmed-critical gate | High |
| `frontend/src/sections/FishMonitoring.tsx` | 135 | Camera + analysis orchestration | Med |
| `frontend/src/sections/BehaviorPanel.tsx` | 133 | Experimental behavior UI | Med |
| `tests/test_water_assessment.py` | 330 | Water engine logic tests | High |
| `tests/test_live_track.py` | 253 | Tracker tests | Med |
| `app.py` | 202 | Streamlit historical viewer | Low (legacy) |
| `evaluate_detection.py` | 199 | Arm A vs B scorer | High |
| `frontend/src/services/thingspeak.ts` | 118 | ThingSpeak client (heart of IoT) | High |
| `backend/api_analysis.py` | 111 | Sampled API analysis (1fps/30cap) | High |
| `extract_behavior_features.py` | 106 | 20-feat extractor (8 centroid +12 keypoint) | High |
| `water_quality_model.py` | 96 | Historical CSV screener (legacy batch) | Med |
| `frontend/src/config/alerts.ts` | 81 | Provisional thresholds + buildAlerts | High |
| `frontend/src/hooks/useLiveCamera.ts` | 230 | Camera loop, quota pause, overlay draw | High |
| `frontend/src/services/historical.ts` | 225 | 30-row static Tilapia RAS extract | Low |
| `backend/history.py` | 69 | JSONL history, key redaction | Med |
| `backend/env.py` | 49 | Minimal dotenv loader | Med |
| `water_quality_dashboard.py` | 25 | Matplotlib 2x2 dump (double-save bug) | Low |

Total (measured, dataset/labels excluded): ~56 `.py` files + 36 `frontend/src` ts/tsx. Core backend ~3000 LOC, frontend ~3000 LOC, tests ~1900 LOC, root scripts ~2000 LOC. Dataset labels: train ~7669 boxes, test 6604 boxes/896 images (proof `eval_detection.json: local.gt_boxes=6604, images=896` + `VALIDATION.md:13-15`).

Entry points:

- Production backend: `backend/main.py:1029-1050` `app = Starlette(routes=[...])`, run `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` (docstring `backend/main.py:6-7`).
- Legacy viewer: `app.py:1-9` `streamlit run app.py` (reads `water_quality_analysis.csv` + `fish_track_quality_summary_corrected.csv` at `app.py:14-15`).
- Frontend: `frontend/src/main.tsx:6` → `App.tsx:19` (hash router `#dashboard/#monitoring` at `App.tsx:17,26`).
- CLI: `school_movement_metrics.py:169-187 main()` (`--video`), `evaluate_detection.py:138-199 main()`, `train_behavior_baseline.py:183-185`.

Dead/unused files (kahin import nahi):

- `app_backup_before_behavior_integration.py`, `backups_dashboard_fix/{app,behavior_model,analyze_video}.py`, `backups_school_movement/app.py` — zero imports found (grep `import app_backup`, `backups_` → no hits). Delete candidate.
- `water_quality_dashboard.py` — standalone, backend/frontend se import nahi; plus double `plt.savefig` bug (line 24-25 same file twice).
- `analyze_video.py`, `view_fish_data.py`, `inspect_dataset.py`, `prepare_dataset.py`, `label_behavior.py` (root) — legacy one-offs, `backend/main.py` se import nahi.
- `frontend/src/services/demo.ts` (8 lines) — `App.tsx`/`api.ts` se import nahi dikha; verify.
- `frontend/dist/*` — build output committed; source se regenerate hota hai, repo mein nahi hona chahiye.
- `.yolov8s-worldv2.pt.*.part`, `~$behavior_review_provisional.xlsx` (temp lock file) — junk.
- `Tilapia RAS Dataset-1.zip`, `seizure_detection_ml_dataset.zip` — duplicate/unrelated zip (seizure dataset ka is project se relation ❓VERIFY NEEDED).

**GAPS:** `requirements.txt` missing hone se LOC-by-dep unverified. `dataset/tilapia_yolo/images` ka size/count `ls` se poori tarah verify nahi kiya (labels se inferred). `backend/data/*` runtime hai, gitignored.

---

## 2. ARCHITECTURE & DATA FLOW

### High-level ASCII

```
[DS18B20 + Turbidity ADC on ESP32] --USB serial--> [Python uploader*] --HTTPS--> [ThingSpeak Channel feeds.json]
        (°C float, ADC 0-4095)         (*code repo mein NAHI mila)          (fields 1-8, read-only)
                                                                              |
                                                                              | GET feeds.json?results=60&api_key=<REDACTED:thingspeak_read_key>
                                                                              | poll >=5s (frontend/src/services/thingspeak.ts:23,97-110)
                                                                              v
[DroidCam/Phone/Browser camera] --> [frontend React] --POST JPEG--> [Starlette backend] --urllib--> [Groq/Gemini LLM + Vision APIs]
   (getUserMedia 1280x720)            (useLiveCamera 1s tick,      (YOLO local OR API vision,      (text + boxes, zero-shot)
    `useLiveCamera.ts:90-99`)         quota-gated 10s)             sanitizer+tracker)
         |                                    | POST /api/videos+analyses            | JSONL (water_readings, history, explanations)
         | upload mp4/mov/avi/mkv/webm        | jobs/<id>/frames.csv,result.json    | `backend/water.py:157-184`
         v                                    v                                    v
[YOLO-seg best.pt + ByteTrack CSVs]  [Water manual form] --> [water.py rule engine] --> [risk.py 5-level] --> [llm.py explain] --> [React panels]
(recorded pipeline, every frame)     (tankId/species/system)   (thresholds JSON)      (NORMAL..CRITICAL)    (cached, cooldown 60s)
```

`*` Python uploader ka code repo mein nahi hai — `LiveSensors.tsx:54` ka label `ESP32 → USB serial → Python uploader → ThingSpeak → dashboard` UI string hai, implementation ❓VERIFY NEEDED.

Har arrow:

| Arrow | Data + format (JSON keys) | Frequency | Sync/Async |
|---|---|---|---|
| ESP32→ThingSpeak | `field1=temp_C float, field2=turb_ADC int` (explicit mapping `VITE_THINGSPEAK_FIELD_*`, else label regex `thingspeak.ts:33-35`) | Device-dependent, ❓VERIFY NEEDED (ThingSpeak free min 15s) | Async (device push) |
| Browser→ThingSpeak | `GET https://api.thingspeak.com/channels/{id}/feeds.json?results=60&api_key=...` → `{channel:{field1..}, feeds:[{created_at, entry_id, fieldN}]}` (`thingspeak.ts:97-100`) | `pollMs = max(5s, VITE_THINGSPEAK_POLL_SECONDS)` (`thingspeak.ts:23`), skip when `document.hidden` (`useSensors.ts:54`), single-flight (`useSensors.ts:24`) | Async fetch + AbortSignal |
| Browser→Backend video | `POST /api/videos multipart file` → `{jobId,videoId}` (`api.ts:56-73`, `main.py:131-176`); `POST /api/analyses {videoId}` → 202 queued (`api.ts:75-76`, `main.py:179-201`) | User-triggered | Async XHR + 1s poll (`useAnalysis.ts:84-89`) |
| Browser→Backend live | `POST /api/live/track?session=<id> body=image/jpeg` → `LiveResult{detections[{box,confidence,outline}],count,inferenceMs,tracks,movement,session}` (`api.ts:85-86`, `main.py:562-606`, `types/index.ts:30-33`) | Preview 1s tick, analyse `max(3s, VITE_LIVE_ANALYZE_MS default 10s)` (`useLiveCamera.ts:10,193-198`), sequential never-overlap (`useLiveCamera.ts:156-157`) | Async, quota pause 60s on 429 (`useLiveCamera.ts:181-183`) |
| Backend→Groq/Gemini | `POST api.groq.com/openai/v1/chat/completions {model,messages:[{image_url data:...}]}` + `generateContent?key=... {contents:[{inlineData}]}` (`vision.py:152-188`, `llm.py:160-202`) | Per sampled frame (recorded: `API_VISION_FPS=1, MAX=30` → max 30 calls/video `api_analysis.py:22-29`; live: ~6/min) | Sync in worker/threadpool (`main.py:538,592`), timeout 60s vision / 25s text |
| Manual→Backend water | `POST /api/water-readings {tankId,species,system,lifeStage,timestamp,source,measurements:{temp:{value,unit},...}}` → `{reading,assessment}` (`water.py:431-449`) | User-triggered | Sync |
| Backend store | `water_readings.jsonl` append, `history.jsonl` append, `explanations.json` cache, `jobs/<id>/{job.json,frames.csv,result.json,original.jpg,annotated.jpg}` | Per request/job | Sync file IO + RLock |

End-to-end flow #1 — "Sensor se data aaya → user ko dikha":

1. `useSensors()` mount → `configProblem()` (`thingspeak.ts:91-95`) — bina `channelId` ke `problem` set, fetch nahi.
2. `refresh()` → `fetchReadings(signal)` (`useSensors.ts:29`, `thingspeak.ts:97`) — URL mein `api_key=<REDACTED>` query param.
3. `parseFeeds(body)` (`thingspeak.ts:67-88`): `feeds` array validate, `resolveMapping` (env wins else single-label match `thingspeak.ts:53-64`), `parseValue` (blank→null, sentinel -127/85→null `thingspeak.ts:38-43`), future `created_at > now+5m` → rejected.
4. `setReadings/mapping/rejected/fetchedAt` (`useSensors.ts:31`), newest `entry_id` se activity log.
5. `MetricCards/HistoryCards/PipelineCard` (`LiveSensors.tsx:77-156`): `statusOf(points,field,refreshOk)` → live/stale/no_data/not_configured (`thingspeak.ts:112-118`), `freshness()` gauge, recharts `AreaChart`, `describeTemperature` insight.
6. `buildAlerts` (`alerts.ts:49-81`) — sirf `live` readings threshold se compare, stale/missing kabhi numeric alert nahi.

End-to-end flow #2 — "AI/ML prediction → kya hota hai":

- Recorded: `UploadPanel select→upload→analyze` (`useAnalysis.ts:48-101`) → `_run()` (`main.py:936-1000`): `vision_backend()==yolo` → `sm.process(video)` every frame → `sm.summarize` → middle-frame `YOLO.predict` → `result.json{reliability:{detections,movement: needs_review/unreliable}, counts:{kind: frame-level, uniqueFish:null}}`; `api` mode → `api_analysis.analyze` sampled 1fps/30cap → same shape + `visionBackend{backend:api}`. UI `ResultsPanel/VideoAnalysis` mein show, `reliability!=reliable` kabhi green nahi.
- Live: `useLiveCamera tick→trackFrame(blob,session)` → `_detect_frame` (`main.py:500-515`) → `_live_predict` YOLO adaptive (`main.py:469-497` → `predict_tiled.detect_adaptive`) OR `_live_predict_api` (`main.py:549-556`) → `_sanitize_live_detections` (`main.py:344-463`) → `live_tracker.update` (`live_track.py:125-234`) → overlay canvas draw (`useLiveCamera.ts:207-226`).
- Behavior: `/api/behavior {trackId|track}` → `_load_tracks(limit 200/5000)` (`main.py:623-639`) → `llm.observe_behavior(track)` (`llm.py:336-354`) → `{observation, experimental:true}`. Centroid-only RF prediction REFUSED (`behavior_live.py:131-142`).

End-to-end flow #3 — "Alert/threshold cross → kya hota hai":

- ThingSpeak path: `buildAlerts` (`alerts.ts:60-67`) live value vs `THRESHOLDS{temperature 25-32, ph 6.5-8.5, do min 5}` (`alerts.ts:8-12`), turbidity ka threshold deliberately absent. Output `AlertPanel` list + `Shell` status badges. Koi sound/push/SMS nahi — UI only.
- Water path: `assess_water` (`water.py:255-348`) per-param `evaluate` (`water.py:201-214`: critical/high exclusive, normal inclusive) → `waterRisk{normal/warning/high/critical/insufficient}` → `risk.assess` (`risk.py:35-137`) 5-level (unconfirmed critical→WARNING, confirmed→CRITICAL) → `RiskPanel/AssessmentReport` + `getExplanation` (cached LLM text, risk override nahi kar sakta `llm.py:206-219` SYSTEM_PROMPT rule 1).

Pattern: **Monolith + modular functions, MVC-ish nahi, event-driven nahi.** Backend ek Starlette process (1 GPU worker `ThreadPoolExecutor(max_workers=1)` `main.py:76`), frontend 2-page SPA, storage files. Kyun: prototype simplicity, no broker/queue/auth. SPOF: (a) single backend process + single-thread GPU queue — ek lamba video sab block karta hai; (b) `backend/data/*.jsonl` + `jobs/` single disk — corrupt/delete = history/readings gone; (c) ThingSpeak channel + Read key — key revoke/channel down = live sensors dead (UI stale dikhata hai, crash nahi); (d) Groq/Gemini quota — 429 pe live/analysis degrade (cooldowns hain, full outage nahi).

**GAPS:** ESP32 uploader code missing — sensor→cloud path code-proof nahi. ThingSpeak `results` default 60 ka time-window unknown (sampling rate ❓VERIFY NEEDED). WebSocket nahi hai — sirf polling (confirm: no `ws`/`socket` in `main.py` routes, no `WebSocket` import).

---

## 3. IoT / CLOUD API INTEGRATION 🔑 (MAX detail)

Cloud platform ka naam: **ThingSpeak (primary IoT cloud) + Groq/Gemini clouds (LLM/vision)**. Custom/MQTT/GPIO/Blynk/Firebase **nahi** — codebase mein `GROQ_URL=https://api.groq.com/openai/v1/chat/completions` (`llm.py:46`, `vision.py:34`), `GEMINI_URL_TMPL=https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` (`llm.py:47`, `vision.py:35`), `ThingSpeak https://api.thingspeak.com/channels/.../feeds.json` (`thingspeak.ts:98`) hi hain.

Exact API endpoints jo call hote hain:

| # | Method + URL pattern | Headers/params | Code jahan call hota hai |
|---|---|---|---|
| T1 | `GET https://api.thingspeak.com/channels/{channelId}/feeds.json?results={N}&api_key={readKey?}` | No auth header; key query param; `fetch(url,{signal})` | `frontend/src/services/thingspeak.ts:97-110` |
| G1 | `POST https://api.groq.com/openai/v1/chat/completions {model,messages,max_tokens,temperature[,response_format]}` | `Authorization: Bearer <REDACTED:groq_key>` | `backend/llm.py:160-175 call_groq`, `backend/vision.py:152-167 _call_groq_vision` |
| G2 | `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=<REDACTED:gemini_key> {system_instruction,contents,generationConfig}` | Key in URL query (quoted) | `backend/llm.py:178-202 call_gemini`, `backend/vision.py:170-188 _call_gemini_vision` |
| Self | `GET /health, POST /api/videos, POST /api/analyses, GET /api/analyses/{id}[ /results|/frames/{kind}], POST /api/live/{detect,track}, GET /api/{llm-status,vision-status,tracks,history,water-*} , POST /api/{behavior,risk,explanation,advice,water-readings}` | CORS `ALLOW_ORIGINS` split, methods GET/POST only | `backend/main.py:1029-1050` + `backend/water.py:487-493 ROUTES` |

Snippet T1 (`frontend/src/services/thingspeak.ts:97-110`):

```ts
export async function fetchReadings(signal: AbortSignal, cfg: ThingSpeakConfig = CONFIG): Promise<ReturnType<typeof parseFeeds>> {
  const url = new URL(`https://api.thingspeak.com/channels/${cfg.channelId}/feeds.json`);
  url.searchParams.set("results", String(cfg.results));
  if (cfg.readKey) url.searchParams.set("api_key", cfg.readKey);
  let res: Response;
  try { res = await fetch(url, { signal }); }
  catch (e) { if ((e as Error).name === "AbortError") throw e; throw new Error("Network error: could not reach ThingSpeak."); }
  // Error messages never include the URL, so the key cannot leak into the UI.
  if (res.status === 400 || res.status === 404) throw new Error(`ThingSpeak refused the request (HTTP ${res.status}). For a private channel, check the channel ID and Read API key.`);
```

Snippet G1 auth (`backend/llm.py:167`): `headers={"Authorization": f"Bearer {api_key}"}` — key memory-only, never logged/returned (proof `llm.py:19-20` docstring + `history.record` filter `history.py:29-30`).

API KEY kahaan se aati hai:

- ThingSpeak Read key: `frontend/.env.local` var `VITE_THINGSPEAK_READ_API_KEY` + `VITE_THINGSPEAK_CHANNEL_ID` (var names confirmed via read, values REDACTED — file read nahi kiya values ke liye). Loaded `thingspeak.ts:18-29 CONFIG{channelId,readKey,results,staleMs,pollMs,fields}` via `import.meta.env`. 🔴 CRITICAL flag: **Vite `VITE_*` bundle mein plaintext hota hai** — code khud warn karta hai (`thingspeak.ts:2` NOTE + `frontend/.env.example:9` + root `.env.example:3-4`). Ye by-design read-only key hai (write key kabhi nahi leta — `thingspeak.ts:1` + `.env.example:8 Never put a Write API key here`), par public repo/bundle mein hone se koi bhi channel read kar sakta hai. Private channel ka data public ho jata hai. Git mein `frontend/.env.local` — `.gitignore:1-4` mein sirf root `.env` hai, `frontend/.env.local` **ignored nahi** → commit risk 🔴 (file exists confirmed, content values check nahi kiye).
- Groq/Gemini keys: root `.env` vars `GROQ_API_KEY`, `GEMINI_API_KEY` (names confirmed, values REDACTED). Loaded `backend/main.py:32 load_dotenv(ROOT/".env")` via `backend/env.py:16-49` (process env wins, missing file never raises). `.gitignore:2 .env` ✅ ignored. Frontend mein kabhi nahi (`api.ts` mein key string zero hits). Server memory only.
- Key scope: ThingSpeak key sirf READ (`fetch` GET only, no write call exists). Kitne devices/sensors is key se jude: code se 1 channel, 4 sensor slots (temp/turbidity/ph/do), field numbers env/label se (actual channel field count ❓VERIFY NEEDED — ThingSpeak response se pata chalega). Groq/Gemini keys se text + vision dono (same key, `llm.py:267-268` + `vision.py:239-240`).

RESPONSE PAYLOAD (real JSON structure, dummy values — code shapes se reconstructed, live capture nahi):

```json
// T1 feeds.json (ThingSpeak documented shape, parser expects `thingspeak.ts:46-50,67-88`)
{
  "channel": {"id": 123456, "name": "<REDACTED>", "field1": "Temperature", "field2": "Turbidity", "field3": "pH", "field4": "DO"},
  "feeds": [{"created_at": "2026-10-16T10:00:00Z", "entry_id": 101, "field1": "29.5", "field2": "2100", "field3": null, "field4": null}]
}
// Har field: string-or-null number-as-string; `parseValue` Number() karke finite check; unit code mein nahi, mapping se (temp °C probe-native, turb ADC raw).
```

Sensor inventory:

| Sensor | Kya measure | Unit | Cloud field/pin | Range | Sampling |
|---|---|---|---|---|---|
| Water temp DS18B20 (ESP32) | Water temp | °C (probe-native, no conversion) | Field 1 explicit `VITE_THINGSPEAK_FIELD_TEMPERATURE` (`SENSORS.md:8`) | Plausible -10..50, rule 25-32 provisional | Device push (❓VERIFY), UI poll ≥5s, stale 5min default |
| Turbidity ADC (ESP32) | Raw ADC | ADC counts (NOT NTU, uncalibrated) | Field 2 explicit (`SENSORS.md:9`) | 0-4095 (12-bit) | Same |
| pH — none installed | — | pH | Unmapped → `not_configured`, rule inactive (`SENSORS.md:10`, `alerts.ts:69-71`) | Rule 6.5-8.5 exists | — |
| DO — none installed | — | mg/L | Unmapped → inactive (`SENSORS.md:11`) | Rule min 5 | — |

POLLING STRATEGY: `useSensors refresh()` + `setInterval(CONFIG.pollMs)` (`useSensors.ts:51-56`), `pollMs = max(5, VITE_THINGSPEAK_POLL_SECONDS default 5)*1000` (`thingspeak.ts:23`), `document.hidden` pe skip, single-flight guard (`useSensors.ts:24 if problem||ctl.current return`), AbortController cleanup, stale seq guard (`useSensors.ts:30 if mine!==seq return`). Cron/webhook nahi, manual `refresh` button bhi (`App.tsx:43 onRefresh`). Code snippet: `useSensors.ts:51-56` upar Sec 2 mein quoted.

Rate limits: ThingSpeak free limit (15s/update, 8000 read cap?) code mein enforce nahi — `results: min(positive(...,60),8000)` (`thingspeak.ts:21`) sirf response size cap hai. Mera code poll min 5s → free-channel 15s limit se **faster poll possible** → 429/throttle risk. 429 aane pe: `!res.ok → throw ThingSpeak returned HTTP 429` (`thingspeak.ts:106`), `setError(msg)` keep-old-readings + mark stale (`useSensors.ts:46`, `statusOf(...,refreshOk=!error)`), activity warn log, auto-retry next interval. Backoff/jitter **nahi** — fixed interval retry. Groq/Gemini vision pe cooldowns hain (`VISION_AUTH_COOLDOWN_S 300, VISION_QUOTA_COOLDOWN_S 120` in `.env.example:39-40`, `_skip_provider/_mark_down` `vision.py:199-220`), text pe auth-skip only (`llm.py:289-290`), quota retry nahi (fail fast).

FAILURE HANDLING (bugs yahin):

- Internet/API down → `Network error: could not reach ThingSpeak` (`thingspeak.ts:103`), old readings kept + stale badge, `Backend unavailable` toasts for backend (`useAnalysis.ts:43,98`). Retry: next poll tick. Backoff nahi.
- Key expire/invalid → ThingSpeak 400/404 → `ThingSpeak refused...check channel ID and Read API key` (no crash); Groq/Gemini 401/403 → provider cooldown + fallback chain (`vision.py:260-287`, `llm.py:286-290 skip.add(provider)`), user message `friendlyLiveError` (`useLiveCamera.ts:24-30`). App crash nahi.
- Timeout set? Vision 60s (`vision.py:62`), text 25s (`llm.py:89`), explanation inflight wait `cooldown+timeout*4+10` (`llm.py:507`). ThingSpeak `fetch` pe **timeout nahi** — AbortController sirf unmount/overlap pe, slow network hang possible 🟡.
- Empty/null/partial/weird → `parseValue null` never 0 (`thingspeak.ts:37-43`), `feeds` non-array → throw `Unexpected response` (`thingspeak.ts:69`), future timestamp → rejected count, blank string → null not error. Backend water: missing stays absent (`water.py:129-130 continue`), NaN/Inf rejected (`water.py:67-68`).
- Duplicate/stale → `entry_id` max tracking (`useSensors.ts:33-41`) duplicate detect nahi (same value repeat normal hai), staleness `now-last.t > staleMs` (`thingspeak.ts:114-117`). Same reading baar-baar aana normal (ThingSpeak last N), code handle karta hai.
- Sensor offline → `no_data` (mapped but zero points) / `not_configured` (field null) / `stale` (old) cards + `AlertPanel` info/warning (`alerts.ts:54-58`), InsightCard `Not enough valid readings` (`LiveSensors.tsx:34`).

CACHING: ThingSpeak data cache nahi (har poll fresh GET, `results=60` window refetch). Local DB mein auto-store nahi — manual `POST /api/water-readings` alag path hai. Backend `explanations.json` cache + `history.jsonl` log only.

Data volume: `results=60` feeds/poll, poll 5s-5min configurable. Example: 5s poll → 17k req/day; ThingSpeak free read limit cross risk. DB growth: manual readings only (few/day), video jobs `frames.csv` (API mode ≤30 rows, YOLO mode full frames e.g. 9000 rows) + 2 JPGs/job. 1 mahine 10 videos/day YOLO → ~GBs (❓VERIFY NEEDED actual video size, `MAX_UPLOAD_MB 500` cap `main.py:43`).

**GAPS:** ESP32 firmware/uploader code + ThingSpeak channel field labels + actual poll/stale env values (values REDACTED, names only) + rate-limit headers verify nahi hue (live call nahi kiya).

---

## 4. AI / ML COMPONENT (MAX detail)

Problem types (3 alag, confuse mat karo):

1. **Fish detection (vision):** object detection + instance segmentation (YOLO-seg) → boxes+masks per frame. Target: `tilapia` single class count/region per frame. Business reason: manual counting aur movement proxy bina human watch ke.
2. **Movement/behavior classification:** zebrafish 5-class (`convulsion/normal swim/posture loss/stationary/whirlpool` in `metrics.json`), tilapia provisional (`behavior_label` in `train_behavior_model.py:31`) — activity categorization, NOT disease diagnosis (code har jagah disclaim karta hai).
3. **Water screening:** NO ML — deterministic rules (`water.py:1-6` docstring `It is not a trained or validated predictive model`). Target `waterRisk`, reason: farmer action triage.

DATASET:

- Detection: `dataset/tilapia_yolo` — train 7669 boxes, test 6604 boxes/896 images, val GX030013 (labels count se inferred; images dir listing truncated, ❓VERIFY NEEDED exact image count). Columns: YOLO-seg polygon lines `class x1 y1 x2 y2 ...` (proof `evaluate_detection.py:37-55 read_gt`). Date range: session IDs GX020019/GX020206 train, GX030013 val, GX010206 test (disjoint sessions, `VALIDATION.md:10-13`). Class balance: single class → N/A. Missing/dup %: ❓VERIFY NEEDED (no EDA script output in repo).
- Zebrafish behavior: `dataset/zebrafish_behavior_prepared/clean_training_samples.csv` → `behavior_features.csv`, n=4413, wells=32, 20 feats, 5 classes (proof `metrics.json` upar). Units coord/frame, FPS undocumented (`extract_behavior_features.py:3-7`).
- Tilapia provisional: `behavior_review_provisional.xlsx` (+ manual review CSVs) — heuristic labels, not visually verified (`train_behavior_model.py:81-83` print).
- Water historical: `dataset/Tilapia RAS Dataset/Documentation/meta_tilapia_set.csv` → 30-row extract `historical.ts:4-222` (duplicates present, e.g. 14:10/14:14 identical — stale/copy artifact).

PREPROCESSING (har step file:line):

- Detection: polygon→box `read_gt` (`evaluate_detection.py:48-54 min/max`), greedy IoU≥0.5 matching (`evaluate_detection.py:69-98 score`), conf 0.35 (`school_movement_metrics.py:19`), plausible-box filter area≤0.40 + span<0.98 (`school_movement_metrics.py:33-44`), mask union via fillPoly (`school_movement_metrics.py:53-59`), downscale 320px for camera/motion (`school_movement_metrics.py:62-65`). No scaling/normalization/encoding (vision).
- Zebrafish: `features(a)` (`extract_behavior_features.py:25-61`): centroid/keypoint speeds, spread, pairdist change, shape change, straightness, CV, frac-moving (>1.0 coord/frame arbitrary per comment line 60). Skips: unreadable/shape≠(60,8,2)/NaN/non-finite (`extract_behavior_features.py:73-90`). No scaling in extractor; `speed_only_logreg` pipeline mein `StandardScaler` (`train_behavior_baseline.py:38-39`), RF mein none (tree, ok). Forbidden identifier cols guard (`train_behavior_baseline.py:67-69`).
- Tilapia provisional RF: `X.replace(inf→nan)`, `valid=X.notna & y!=""` (`train_behavior_model.py:29-33`), `train_test_split test 0.25 stratify random 42` (`train_behavior_model.py:38-40`), RF 200 balanced (`train_behavior_model.py:42-46`). Outlier/scaling/encoding nahi.
- Water legacy batch: `pd.to_numeric errors=coerce` (`water_quality_model.py:57`), per-param min/max compare (`water_quality_model.py:28-38`).

⚠️ DATA LEAKAGE CHECK:

- Zebrafish baseline ✅ SAFE: `StratifiedGroupKFold(n=5, groups=well_id)` (`train_behavior_baseline.py:81`), hard assert `not set(groups[tr]) & set(groups[va])` (`train_behavior_baseline.py:90-91`), seed search for coverage, no scaler-fit-leak (pipeline per-fold fit `train_behavior_baseline.py:113-121`). Time-series nahi (independent wells), chronological split N/A.
- Tilapia provisional RF 🔴 CRITICAL LEAK RISK: `train_test_split random stratify` on track-level rows (`train_behavior_model.py:38-40`) — same video/session ke tracks train+test dono mein ja sakte hain (session split nahi, group split nahi). Metrics agreement-with-pseudo-labels hain, real accuracy nahi (code khud kehta hai lines 81-83). Scaling nahi (RF → leak N/A), par split leak + label leakage (heuristic labels se train karke unhi pe eval) → inflated.
- Detection ✅ SAFE: session-disjoint train/val/test (`VALIDATION.md:10-13`), eval inference-only (`evaluate_detection.py:101-120 local_arm` no fit).

MODELS + hyperparams + final choice:

- Detection final: local `tilapia_seg best.pt` (F1 0.9577) evidence-winner, par operator override se default API-first (`main.py:50-73 vision_backend()`, `VALIDATION.md:27-33`). Hyperparams: conf 0.35 recorded / 0.20 live (`main.py:250-253` comment recall-first), imgsz 640, tile trigger 0.25 edge_min 0.10 (`main.py:261-267`). Final choice reason code mein honest trade-off comment (`main.py:59-63`).
- Zebrafish: majority Dummy vs speed-logreg vs RF300 balanced min_leaf 3 (`train_behavior_baseline.py:35-43`); winner RF pooled macro-F1 0.726 acc 0.801 vs logreg 0.606/0.714 vs dummy 0.137/0.523 (proof `metrics.json` Sec 3 bash output). Choice: RF (best CV, still zebrafish-only).
- Tilapia RF: n_est 200 balanced random 42 (single split, no CV) — final nahi hona chahiye (provisional).

EVALUATION exact numbers:

- Detection local: P=0.9429 R=0.9729 F1=0.9577 TP6425 FP389 FN179 896 imgs 26.6ms/img cuda (`eval_detection.json` bash dump). Train vs test gap: train metrics ❓VERIFY NEEDED (not in repo) — overfitting claim nahi kar sakte. Confusion/ROC N/A (detection).
- Zebrafish RF pooled: macro-F1 0.7261 acc 0.8010 recall per-class conv 0.663 normal 0.743 posture-loss 0.561 stationary 0.878 whirlpool 0.844; fold mean 0.720±0.078 (proof metrics.json). Overfitting: final model all-wells fit, CV OOF metrics reported (correct, `train_behavior_baseline.py:149-156` note `NOT evaluated on held-out`).
- Tilapia provisional: accuracy vs provisional labels single split (value repo mein saved `behavior_test_predictions.csv` mein, console print only — ❓VERIFY NEEDED rerun number). Overfitting: test small + pseudo-labels → meaningless.

Model artifacts:

| Artifact | Path | Size/date | Load | Inference time |
|---|---|---|---|---|
| YOLO-seg | `runs/segment/runs/aquaculture/tilapia_seg/weights/best.pt` (via `sm.DETECTOR`) | ❓VERIFY NEEDED (weights/ excluded from scan) | `YOLO(path)` lazy per backend (`main.py:481-483`, `_live_model` cached) | 26.6ms/img cuda eval; live `inferenceMs` per response |
| Zebrafish RF | `runs/behavior_baseline/random_forest_baseline.joblib` + `rf_feature_importance.csv` | ❓VERIFY size/date | `behavior_live.load_model` + strict feature check (`behavior_live.py:39-55`) | `predict_proba` 1×20 row (ms) |
| Tilapia prov RF | `behavior_random_forest.joblib` (`saved[model,features]` 7 feats) | ❓VERIFY | `behavior_model.py:12-14 joblib.load` | Batch per-track |
| API vision | No artifact (cloud) | — | Per-call downscale 768px JPEG82 (`vision.py:90-100`) | Seconds/call (❓VERIFY live) |

⚠️ TRAIN-SERVE SKEW — classic bug, yahan **caught by design**:

- Training feats 20 (`extract_behavior_features.features` 20 keys lines 40-60) vs live centroid 8 (`behavior_live.CENTROID_FEATURES` 8 lines 27-32, `KEYPOINT_ONLY 12` line 32). `classify_centroid_window` hamesha `features_incompatible` return karta hai (12 missing) — prediction kabhi nahi (`behavior_live.py:131-142`). `app.py:171-176` UI bhi `features_incompatible` ko honestly show karta hai. So skew bug nahi, guard hai. Lekin `behavior_model.py` (7-feat tilapia RF on `fish_movement_features.csv`) vs `behavior_live` (20-feat zebrafish) — **do alag feature spaces, do alag models, naam similar** → confusion risk (Sec 9 bug).
- Water: training `water_quality_model.py` simple min/max vs serving `water.py` bands+stale+contradictory+persistence — **logic skew** (same thresholds base, different semantics; legacy batch `status REVIEW REQUIRED` vs serving `waterRisk/critical gate`). Compare: `water_quality_model.py:33-36 LOW/HIGH` vs `water.py:201-214 evaluate exclusive above/below` + `risk.py:56-64 confirmed gate`. Same input alag output de sakta hai.

Live inference flow (naya reading → model → output): Sec 2 flow #2 dekho. Retraining plan: **nahi** (no script schedule, no drift monitor, `metrics.json limitations` single-well warning only). Drift handle nahi hota.

Agar ML fake/hardcoded/if-else: **Water + risk + alerts 100% if-else rules hain (honestly labeled `rule_based_screening`, `experimental`)** — fake ML nahi, no-ML-by-design. Behavior tilapia RF pseudo-labels pe hai (provisional, must not use). Detection YOLO real trained, API vision zero-shot.

**GAPS:** Train-set detection metrics, zebrafish raw FPS/units, tilapia label protocol, API-vision scored eval (Blocked), feature importance interpretation — sab ❓VERIFY NEEDED / Blocked.

---

## 5. BACKEND / SERVER CODE

Framework: **Starlette** (FastAPI nahi, `main.py:21` import), version ❓VERIFY NEEDED. Start: `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` (`main.py:6-7`). `JOBS` dir init + `water.init` + `_fail_interrupted` at import (`main.py:1025-1027`).

HAR route table:

| Method | Path | Kaam | Auth? | Request example | Response example | Errors |
|---|---|---|---|---|---|---|
| GET | `/health` | Model/vision/LLM status | No | — | `{status:ok, model_available, model_validated:false, vision_backend:api\|yolo, llm:{groq_configured,gemini_configured}}` (`main.py:116-128`) | — |
| POST | `/api/videos` multipart `file` | Upload + magic-byte + decode + frame-limit check | No | `FormData file=*.mp4` | `{jobId,videoId,status:uploaded}` (`main.py:131-176`) | 400 no file, 413 >500MB, 415 ext/magic mismatch, 422 undecodable |
| POST | `/api/analyses` | Queue job (failed retry allowed) | No | `{"videoId":"<32hex>"}` | 202 `{jobId,status:queued}` (`main.py:179-201`) | 400 bad JSON, 404 unknown, 409 already queued/processing/completed, 503 no weights/keys |
| GET | `/api/analyses/{job_id}` | Job state | No | — | `{jobId,state,error,filename,createdAt}` (`main.py:204-209`) | 404 unknown |
| GET | `/api/analyses/{job_id}/results` | result.json (completed only) | No | — | `AnalysisResult` (Sec 6 types) | 404/409 not completed |
| GET | `/api/analyses/{job_id}/frames/{original\|annotated}` | JPG preview | No | — | `image/jpeg` (`main.py:222-228`) | 404 |
| POST | `/api/live/detect` body JPEG/PNG | Stateless frame detections + sanitize | No | `Content-Type: image/jpeg <3MB` | `LiveResult{detections,count,inferenceMs,timestamp,validated:false,note[,rejected,review]}` (`main.py:518-546`) | 400 empty, 413 >3MB, 415 undecodable, 500 sanitized, 503 no backend |
| POST | `/api/live/track?session=<id>` | + greedy tracks + movement | No | Same + `?session=abc-123` regex `^[A-Za-z0-9_-]{1,64}$` (`main.py:559`) | Above + `{tracks,movement,session}` (`main.py:562-606`) | 422 bad session, others same |
| GET | `/api/llm-status`, `/api/vision-status` | Key presence + chains (no secrets) | No | — | `{groq_configured,gemini_configured,...}` (`llm.py:109-123`, `vision.py:74-86`) | — |
| GET | `/api/tracks?limit=200` | CSV top tracks (obs desc) | No | — | `{tracks:[{track_id,observations,...}]}` (`main.py:642-649`) | 404 no CSV |
| POST | `/api/behavior` | LLM movement observation (RF replaced) | No | `{"trackId":1}` or `{"track":{observations,...}}` | `{provider,model,observation,experimental:true}` (`main.py:652-691`) | 400/422/404/502/503 |
| POST | `/api/risk`, `/api/explanation`, `/api/advice` | Risk doc / cached structured explain / free-text advice | No | `{"tankId":"...","jobId":"...?"}` (either required) | `RiskDocument` / `ExplanationResponse+cached` / `{advice,...}` (`main.py:796-860,749-763`) | 400/422/404/429 cooldown/502/503 |
| GET | `/api/history?limit=&event=` | Newest-first records | No | — | `{records,skippedLines}` (`main.py:863-871`, max 200 `history.py:16`) | 422 bad limit |
| GET/POST | `/api/water-config`, `/api/water-readings`, `/api/water-assessment`, `/api/assessment` | Rules/CRUD/combined | No | `WaterPayload` (Sec 4) | `WaterAssessment/CombinedAssessment` (`water.py:424-485`) | 400/422 fields/404 |

Controller/service separation: **partial** — routes `main.py`, engines `water/risk/llm/vision/history/live_track/api_analysis` alag, par `_sanitize_live_detections/_box_iou/_poly_area_frac/_detect_frame/_run/_video_result/_combined_from_request` sab `main.py` mein (400+ lines fat file). God-file smell (Sec 10).

Middleware: CORS only (`main.py:1049 allow_origins=ORIGINS split, allow_methods GET/POST, allow_headers *`). **Missing:** auth, rate-limit, request-id, logging middleware, global error handler (per-route try + `_err` only), compression, helmet headers.

Background jobs: `ThreadPoolExecutor(max_workers=1)` serial GPU (`main.py:76`), `_pool.submit(_run,d)` (`main.py:200`), no cancel (`useAnalysis.ts:103` comment `There is no server-side cancel`), restart-interrupted → failed (`main.py:1014-1027`). Threads: explanation inflight dedup (`llm.py:441-442`), live YOLO lock (`main.py:232`), job RLock (`main.py:75`), history RLock. Async: `run_in_threadpool` for blocking (`main.py:538,592,643,683`).

WebSocket/real-time: **nahi** — polling only (1s job poll, 5s+ sensor poll, 10s live analyse).

Error handling: try/catch har I/O boundary pe (`upload/start/live_track/behavior/advice/risk/explanation/_run`), **nahi** hai: `load_rules()` JSON parse pe (corrupt `water_rules.json` → 500 unhandled), `_read` JSON parse pe (corrupt `job.json` → 500), `assess_water` `datetime.fromisoformat` pe (corrupt timestamp → 500), `prepare_frame` ke bahar (covered), frontend `checkHealth` non-JSON (covered via res.ok only). Global handler nahi, errors user ko `{error: msg[:300-600]}` JSON + path redaction regex (`main.py:540,596,995-996`). Sensitive leak guard: history key filter + LLM prompt caps 6000 chars (`llm.py:250`).

Logging: `print` startup (`main.py:277-279`), `logging info detect_adaptive ms` (`predict_tiled.py:148-150`), `aqua.sanitize debug` rejects (`main.py:415-452`). Levels ad-hoc, no file rotation (stdout → `backend_uvicorn.log` files exist, content ❓VERIFY NEEDED — not read). Sensitive log nahi (keys never in logs per `env.py:10`, `llm.py:19-20`).

**GAPS:** uvicorn access logs content, MAX_UPLOAD/FRAMES env actuals, concurrent upload DoS test — verify nahi kiya (server run nahi kiya).

---

## 6. FRONTEND / UI / DASHBOARD

Framework: React 19 + Vite 8 + Tailwind 4 + Recharts + lucide-react + framer-motion (`package.json:11-26`). Pages: **2** (`App.tsx:17 pageFromHash dashboard|monitoring`, `Shell` nav). Components ~15 sections + 5 base.

Har page:

| Page/Section | Route | Kya dikhata | Data kahaan se | File |
|---|---|---|---|---|
| Dashboard Insight+Pipeline+Metrics+Alerts+History+Activity | `#dashboard` | ThingSpeak live cards, freshness, temp insight | `useSensors→thingspeak.ts` | `App.tsx:45-53`, `LiveSensors.tsx`, `StatusPanels.tsx:28-67` |
| WaterAssessment+Risk+WaterQuality | `#dashboard` lower | Manual form, rule assessment, risk doc, historical charts | `POST/GET /api/water-*, /api/risk` + `historical.ts` | `WaterAssessment.tsx:12-81`, `RiskPanel`, `WaterQuality.tsx` |
| FishMonitoring (camera+upload+results+behavior) | `#monitoring` always-mounted (`App.tsx:54-57` comment loop keeps running) | Live overlay, job progress, detections, LLM observation | `useLiveCamera`, `useAnalysis`, `/api/live/*`, `/api/behavior` | `FishMonitoring.tsx:135`, `UploadPanel`, `VideoAnalysis`, `ResultsPanel`, `BehaviorPanel` |
| Header/Shell/Toasts | All | Status badges, refresh, toasts | `useBackendState /health 15s` (`useBackendState.ts:18`) | `Shell.tsx`, `Header.tsx`, `Toasts.tsx` |

Component tree: `MotionConfig>Shell(status,fetchedAt)>[dashboard: Insight+Pipeline, MetricCards, AlertPanel, History+Activity, WaterAssessment>WaterForm+AssessmentReport+AiAdvisor, RiskPanel, WaterQuality] + [monitoring: FishMonitoring(cam,a)] + footer disclaimer` (`App.tsx:40-64`). State: local `useState` per hook, no Redux/Zustand/context — `sensors/cam/analysis/backend` prop-drilled.

Data fetching: `fetch` + `XMLHttpRequest` (upload progress `api.ts:56-73`), polling intervals 1s job (`useAnalysis.ts:87`), 5s+ sensors (`useSensors.ts:54`), 15s health (`useBackendState.ts:18`), 1s preview/10s analyse live (`useLiveCamera.ts:146-201`). Loading states ✅ (Connecting…/Loading…/Starting…), error states ✅ (`Fetch Failed`, `Backend unavailable`, quota pause `cooldownUntil`), empty states ✅ (`No readings`, `Not enough readings`, `No activity yet`).

Charts: **Recharts** `AreaChart` (`LiveSensors.tsx:141-147 isAnimationActive=false`), `st.line_chart/bar_chart` Streamlit legacy (`app.py:69-78,98`). Real-time: sensor charts refetch poll pe re-render, live overlay canvas per result (`useLiveCamera.ts:207-226`). Refresh karna nahi padta (auto-poll), par stale data clearly labeled.

Forms/validation: client `WaterForm` (config-driven units/methods) + server `validate()` strict (`water.py:88-153`: tank regex, species/system enum, ISO+tz timestamp, future+10yr-old reject, supersedes id check, unit whitelist, plausible range, ammonia method required). Server-side authoritative ✅.

Responsive: Tailwind grid `grid-cols-1 sm:2 xl:4` (`LiveSensors.tsx:80`), `max-w-[1536px]` (`App.tsx:44`). Mobile pe camera + upload chalega (getUserMedia HTTPS/localhost needed — `alerts.ts:74 unsupported` message). A11y: `aria-label` on cards/history (`LiveSensors.tsx:31,80`), canvas overlay screen-reader invisible 🟡, color-only status dots (text label bhi hai ✅).

🚨 UI PERFORMANCE: har render pe API call **nahi** (interval-gated + single-flight + hidden-tab skip). `useNow(1000)` per-card re-render (`LiveSensors.tsx:19-23`) — 1s full MetricCards re-render, cheap (4 cards). `useEffect` deps: `refresh` memoized on `[problem,log]` (`useSensors.ts:49`) — `log` stable (`useCallback []`), ok; `useLiveCamera tick` dep `[status]` only (`useLiveCamera.ts:201`) — `backendConfigured` const, ok; `WaterAssessment refresh` dep `[jobId]` + `tank` effect (`WaterAssessment.tsx:22-34`) — job change pe double fetch (history+combined) expected. Infinite loop risk low. Heavy list: history slice 6 (`useAnalysis.ts:59`), activity slice 20 (`useSensors.ts:21`), live history slice 120 (`useLiveCamera.ts:176`), tracks limit 200 (`main.py:623`) ✅ paginated-ish. Recharts 30-60 points fine.

⚠️ CRITICAL check — kya frontend directly cloud API hit karta hai? **HAAN — ThingSpeak ko directly browser se hit karta hai** (`thingspeak.ts:98 api.thingspeak.com`), aur **Read API key browser bundle mein expose hoti hai** (`thingspeak.ts:2` NOTE). Ye **by-design read-only** hai (write key kabhi nahi), par 🔴 CRITICAL scope mein: private channel data + quota abuse (koi bhi key nikaal ke poll kar sakta hai). Groq/Gemini keys kabhi frontend mein nahi ✅ (only backend `os.environ`). Fix: ThingSpeak ko backend proxy se serve karo (key server-side, response cache + rate-limit), ya public channel + read-key rotation + referrer restriction (ThingSpeak mein limited). Sabse pehle fix list mein #1 (Sec 8/14).

**GAPS:** Visual render check nahi kiya (dev server run nahi), Lighthouse/a11y audit nahi, DroidCam auto-switch real device pe verify nahi.

---

## 7. DATABASE / DATA STORAGE

DB type: **koi RDBMS nahi — files only** (SQLite/MySQL/Postgres/Mongo/Firebase **nahi**). CSV-only + JSONL.

Connection/credentials/pooling: N/A (file paths). `water.init(JOBS.parent, job_result)` (`main.py:1026`) sets `data/backend/data/` (env `AQUA_BACKEND_DATA` override `main.py:42`, `history.py:20-21`, `llm.py:446-447`). Credentials file mein nahi (keys env only).

HAR table/collection schema:

| Store | Columns/keys | Types | Nullable/default | Constraints/indexes |
|---|---|---|---|---|
| `water_readings.jsonl` 1 JSON/line (`water.py:173-177 append`) | `id 32hex, createdAt ISO, tankId, species, lifeStage?, system, timestamp ISO, source, supersedes?, measurements{param:{value,unit,canonicalValue[,method]}}` (`water.py:151-153`) | strings/numbers | lifeStage/supersedes null ok; missing params absent (never 0) | No index; `current_records` filters tank + superseded set per-read (`water.py:180-184`); `known_ids` per-tank for supersedes (`water.py:440`) |
| `history.jsonl` | `ts, event, tank_id?, job_id?, status?, provider?, model?, ...` (`history.py:27-34`, key-like fields dropped) | strings | all optional except ts/event | No index; `query` full-scan + sort desc + limit 200 (`history.py:64-69`) |
| `explanations.json` `{scope: {evidence_hash,response,provider,model,generated_at}}` (`llm.py:443-460`) | scope `tank:job` (`main.py:843`) | object | — | Dict lookup; tmp-write+replace atomic (`llm.py:462-470`) |
| `jobs/<32hex>/job.json` | `id,filename,state,video,createdAt,error` (`main.py:174-175`) | strings | error null ok | `ID_RE ^[0-9a-f]{32}$` (`main.py:47`), atomic tmp replace (`main.py:92-96`), RLock |
| `jobs/<id>/frames.csv, result.json, original/annotated.jpg` | frame rows / result doc / JPEGs | — | — | No retention |
| CSVs (`water_quality_analysis.csv`, `fish_track_quality_summary_corrected.csv`, `school_movement_*.csv`, `fish_movement_features*.csv`, `behavior_*.csv`) | Mixed (temp/pH/DO/turb + track_id/obs/speeds) | floats/strings | — | No schema enforcement (Streamlit `required_*` check `app.py:24-39` only) |

ER ASCII:

```
[tankId 1]--<*[water_readings] (supersedes self-FK: record.supersedes -> record.id, same tank)
[tankId ?]--<*[history events] (no FK, loose tank_id/job_id strings)
[tank:job 1]--1[explanation cache] (evidence_hash compare)
[job 1]--1[job.json + frames.csv + result.json + 2 JPGs] (filesystem, no DB FK)
```

Migrations: **nahi** (tool/p count 0). Pending/conflict N/A.

Query patterns: `read_all()` full-file scan per request (`water.py:161-170`, `history.py:46-61`) — N+1 nahi (single scan), par **missing index**: har `POST /api/water-readings` + `GET assessment` poori file padhta hai (10k lines → slow). Bina LIMIT: `get_readings` tank filter ke baad **all rows desc return** (`water.py:452-463` no limit — 10k readings = MBs response 🟠). `list_tracks` limit 200 ✅, `history` limit 200 ✅. DB call loop ke andar: `_combined_from_request` mein `read_all` per advice/risk/explain call (3x same scan if UI parallel) 🟡. `load_rules()` har call pe 2 JSON reads (`water.py:43-54`) — edit-without-restart ke liye, cache nahi.

Retention: **infinite** — purana data delete/archive kabhi nahi (no cron, no TTL except live sessions 60s `live_track.py:30`). `backend/data/` gitignored (` .gitignore:3`) par disk full risk.

Backup: **nahi** (no script, no docs).

**GAPS:** File sizes/row counts measure nahi kiye (CSVs ke `wc -l` pending), concurrent append corruption test nahi (RLock process-local only — multi-worker uvicorn unsafe, Sec 9 bug).

---

## 8. SECURITY AUDIT 🔴

| # | Point | Verdict | Proof file:line |
|---|---|---|---|
| S1 | Backend keys hardcoded? | ✅ SAFE | Keys sirf `os.environ.get("GROQ_API_KEY")` (`llm.py:96-97,267-268`, `vision.py:55-56,239-240`); no literal `gsk_/AIza` in backend/src (grep hits only tests fake + docs) |
| S2 | `.env` committed? | ✅ SAFE (root) / ⚠️ RISK (frontend) | Root `.env` exists + `.gitignore:2 .env` ✅; `frontend/.env.local` exists aur `.gitignore` mein **nahi** → commit risk 🔴 if pushed. Values check nahi kiye (REDACTED) |
| S3 | Git history leak? | ❓VERIFY NEEDED | `git log` check nahi kiya (repo `.git` scan se excluded per instructions). `gh secret scanning` chalao |
| S4 | Frontend bundle key? | 🔴 CRITICAL (by-design read-only) | `thingspeak.ts:2 NOTE VITE_* bundled`, `CONFIG.readKey` in bundle (`thingspeak.ts:20`), URL `?api_key=` browser devtools mein visible. Write-scope nahi (read-only ✅), par private data + quota exposure |
| S5 | SQL injection | ✅ SAFE | No SQL (no raw queries, no ORM). JSONL only |
| S6 | Command injection | ✅ SAFE | No shell/exec; `cv2.VideoCapture(str(video))` path only, `job_id` regex-gated (`main.py:80-84 _dir`) |
| S7 | XSS | ⚠️ RISK | React escapes by default ✅; par `dangerouslySetInnerHTML` grep nahi kiya (❓VERIFY), LLM `advice/observation` text render hota hai (`AiAdvisor/BehaviorPanel` — escaping React default pe bharosa). Markdown render hai to sanitise check karo |
| S8 | AuthN/AuthZ login? | 🔴 CRITICAL (missing) | Koi login/JWT/session nahi — **har endpoint open** (routes table Sec 5 Auth?=No). Localhost prototype ke liye ok, LAN/internet expose pe anyone can upload/analyse/read tanks |
| S9 | Passwords hashed? | N/A | No passwords (N/A, bcrypt nahi chahiye) |
| S10 | JWT secret/expiry? | N/A | No tokens |
| S11 | Sensitive endpoint w/o auth? | 🔴 CRITICAL (same as S8) | `/api/water-readings` (PII-ish tank data), `/api/videos` (arbitrary video upload 500MB), `/api/history` — sab open |
| S12 | CORS `*`? | ⚠️ RISK | `allow_origins=ORIGINS` split (`main.py:45,1049`) default localhost only ✅, par `allow_headers=["*"]` + no `allow_credentials` explicit. `*` origin nahi (good). Env override se `*` set ho sakta hai — docs mein warn nahi |
| S13 | Rate limiting? | 🔴 CRITICAL (missing backend) | Backend mein **zero** rate-limit (upload size 413 + frame-count 422 only). 500MB upload loop / live 3MB/req flood / LLM cost flood possible. Frontend poll floors hain (5s/10s) par attacker bypass kar sakta hai |
| S14 | Input validation? | ✅ SAFE (backend) / ✅ (frontend) | Water `validate()` strict (`water.py:88-153`), video magic-byte+decode+frame-cap (`main.py:107-176`), session regex (`main.py:559`), tank/name regex (`water.py:26-27`). Cloud input `parseValue` finite-only. Direct use nahi |
| S15 | File upload checks? | ✅ SAFE mostly | Ext whitelist (`main.py:46`), magic bytes ftyp/RIFF/EBML (`main.py:107-112`), empty/0-fps/frame-cap reject, size streaming cap (`main.py:153-159`), `_clean_name` (`main.py:103-104`). Path traversal: `video{ext}` fixed name ✅, `kind` whitelist (`main.py:225`). Missing: content-type sniff bypass + decompression bomb (500MB mp4 CPU) ⚠️ |
| S16 | Vuln deps? | ❓VERIFY NEEDED | `frontend/package-lock.json` present (pin ✅ floating `^` in package.json). `npm audit`/`pip audit` chalaya nahi. Backend versions unknown (no lock) |
| S17 | Key rotation/min scope? | ⚠️ RISK | Groq/Gemini full-account keys (scope ❓VERIFY dashboard), rotation manual (env restart). ThingSpeak read-only min-scope ✅ (write key kabhi config nahi). Key 10 jagah copy nahi (2 backend modules env se, 1 frontend env se) ✅ |
| S18 | Secrets in logs/errors? | ✅ SAFE | Path redaction regex (`main.py:540,596,995`), ThingSpeak URL never in error (`thingspeak.ts:104`), history key-drop (`history.py:29-30`), `load_dotenv` never logs values (`env.py:10`) |
| S19 | Pickle/joblib load? | ⚠️ RISK | `joblib.load(MODEL_PATH)` (`behavior_model.py:12`, `behavior_live.py:44`) — arbitrary code exec if file tampered. Guard: own artifact + structure/feature check (`behavior_live.py:49-54`), warning comment line 40-41. Mitigation: checksum + read-only perms pending |
| S20 | Multi-worker file race? | ⚠️ RISK | RLock process-local only (`main.py:75`, `water.py:28`); `uvicorn --workers>1` pe JSONL interleave/corrupt (Sec 9 bug) |

Prioritised FIX LIST (top 10, khatarnak pehle):

1. **ThingSpeak Read key exposure** (`thingspeak.ts:18-29`, `frontend/.env.local`): backend proxy `/api/sensors/live` (key server-side, 15s cache, per-IP limit) + `.gitignore` mein `frontend/.env.local` add + key rotate. Effort M, risk: private data + quota theft band.
2. **No auth + no rate-limit** (`main.py:1029-1050` all open): token (Bearer env) + per-IP token bucket (slowapi) + upload/day cap. Effort M/L. Risk: abuse/cost/DoS band.
3. **`frontend/.env.local` git risk**: `.gitignore` add + `git rm --cached` + history scan (`gitleaks`). Effort S.
4. **Unbounded `GET water-readings`** (`water.py:452-463`): `?limit=&cursor=` + default 200 + max 1000. Effort S.
5. **500MB upload DoS** (`main.py:43-44,145-159`): lower default (100MB), add per-IP/day quota, virus/type re-check via ffprobe, async virus-scan hook. Effort M.
6. **CORS `allow_headers *` + env `*` origin footgun** (`main.py:1049`): explicit headers list + startup warn if `*`. Effort S.
7. **Joblib pickle** (`behavior_live.py:44`): sha256 pin + `allow_pickle` audit + artifact perms 444. Effort S.
8. **Multi-worker corruption** (`water.py:173-177`, `history.py:38-43`): file-lock (portalocker) or SQLite-WAL migrate. Effort M.
9. **ThingSpeak no-timeout hang** (`thingspeak.ts:102`): `AbortSignal.timeout(10000)` + exponential backoff + `Retry-After` respect. Effort S.
10. **XSS via LLM markdown** (❓VERIFY render path): `DOMPurify` + plain-text default. Effort S. Pehle `grep -rn dangerouslySetInnerHTML frontend/src` chalao.

**GAPS:** `npm/pip audit`, `gitleaks`, ZAP/Burp dynamic scan — chalaye nahi (network/run nahi kiya).

---

## 9. KNOWN BUGS, ERRORS & SMELLS 🐛 (main maqsad — max mehnat)

| # | Sev | File:Line | Bug/Issue | Symptom | Root cause | Suggested fix (code level) |
|---|---|---|---|---|---|---|
| B1 | 🔴Blocker | `backend/main.py:65-73` + `VALIDATION.md:27-33` | API-first override unevaluated default | Live/recorded counts zero-shot, masks nahi, farmer galat decide karega | Operator override ne evidence-winner (YOLO F1 0.9577) ko bypass kiya; Arm B BLOCKED | Default `yolo` wapas ya `AQUA_VISION_BACKEND` required-explicit; UI banner `API unevaluated` jab `visionBackend==api` |
| B2 | 🔴Blocker | `frontend/.env.local` + `thingspeak.ts:20` | Read key bundle/public + git risk | Koi bhi key nikaal ke private channel padhega, quota uda dega | VITE_* plaintext + `.gitignore` miss | Sec 8 Fix #1/#3 (proxy + ignore + rotate) |
| B3 | 🔴Blocker | `backend/main.py:1029-1050` (all routes, no auth/limit) | Open upload + LLM cost flood | 500MB loop se disk/GPU/cost DoS | No authN, no throttle, single GPU queue | Bearer + bucket + quota (Sec 8 #2) |
| B4 | 🟠High | `water_quality_model.py:68-72` vs `water.py:340,389-396` | Legacy batch vs serving risk skew | Same CSV do system mein alag status | Batch `REVIEW REQUIRED` simple OR vs serving `waterRisk+confirmed gate+stale` | Batch ko `water.assess_water` reuse karwao ya `water_quality_model.py` ko deprecated mark + `app.py` warning |
| B5 | 🟠High | `train_behavior_model.py:38-40` | Random session-agnostic split + pseudo-label eval | Accuracy inflated, tilapia pe deploy pe fail | No GroupKFold, heuristic labels | `train_behavior_baseline.py` discipline reuse (well/session groups) + label protocol; provisional model ko prod se hatao |
| B6 | 🟠High | `backend/water.py:452-463 get_readings` | Unbounded tank history return | 10k readings → MBs, UI hang | No limit param | `?limit=200&before=` + `MAX_LIMIT 200` like history |
| B7 | 🟠High | `backend/water.py:161-170 read_all` per-request full scan | O(N) per risk/explain (3x parallel) | Latency + file contention | No cache/index | In-memory append cache + mtime check ya SQLite |
| B8 | 🟠High | `water_quality_dashboard.py:24-25` | Double `plt.savefig` same file | 2x render time, confusion | Copy-paste | Dusri line hatao |
| B9 | 🟠High | `frontend/src/services/historical.ts:4-222` duplicates | Identical timestamps repeated (14:10/14:14 same values) | Trend flat/avg biased | Static extract mein dup rows | Dedupe by `(t+values)` + source note; `getWaterQuality` (`api.ts:93-100`) dead? use check karo |
| B10 | 🟡Med | `backend/main.py:344-463 _sanitize` + `live_track.py:147-158 motion gate` | Static decor fish ban sakta hai (gate aggressive) | Real slow fish missing | `MOTION_DIFF_MIN 25/255` + need 3/5 frames | Gate metrics expose (`motion_gated` already ✅) + threshold env + eval on static video |
| B11 | 🟡Med | `backend/main.py:282-284 _thin` + `predict_tiled.py:46-48` duplicate | Outline thinning dup code | Drift risk | DRY violation | `main._thin` ko `predict_tiled._thin_pts` reuse |
| B12 | 🟡Med | `frontend/src/services/api.ts:23 BASE` prod empty | Prod build bina env ke backendConfigured=false → silent demo | User soche live hai, demo hai | Empty default prod | Build-time assert + UI `Demo mode` banner (already partial `WaterAssessment.tsx:75`) global karo |
| B13 | 🟡Med | `backend/main.py:236-248 _env_float/_env_flag` silent fallback | Bad env (`AQUA_CONF=abc`) silently default | Misconfig invisible | except→default no warn | Startup log + `/health` echo effective values |
| B14 | 🟡Med | `backend/water.py:287 DO>1.5*saturation → contradictory` | Saltwater/altitude pe false contradictory | Good reading flagged | Freshwater sea-level formula only (`water.py:193-194`) | Salinity/altitude input + formula branch ya message soft karo |
| B15 | 🟡Med | `app.py:43 short_tracks str.contains` NaN crash risk | `review_reasons` NaN → AttributeError? | Dashboard crash on dirty CSV | `.str.contains` na=False missing (`app.py:43`) | `str.contains("short track", na=False)` |
| B16 | 🟡Med | `app.py:102 fish['fps_used'].iloc[0]` | Empty fish CSV → IndexError | `st.error` ki jagah crash | No empty guard | `if fish.empty: st.stop()` |
| B17 | 🟡Med | `behavior_model.py:23-27 FPS derive` median div | Single-frame tracks → `_d` empty → median NaN → ValueError (good fail, par message generic) | Batch abort | No per-track fallback | Fail-fast ok, message mein track count + file name add karo |
| B18 | 🔵Low | `frontend/src/sections/LiveSensors.tsx:85 lo/hi` empty bars | `bars=[]` → `Math.min(...[]) = Infinity` (bars.length guard ✅ line 103, par lo/hi compute pehle) | `hi===lo` false, height NaN? | Guard order | `const [lo,hi] = bars.length ? [...] : [0,1]` |
| B19 | 🔵Low | `backend/main.py:166-168 fps/frames` | `fps` NaN truthy? `not fps` catches 0/NaN? NaN truthy hota hai JS nahi Python mein — Python `not float('nan')` False → NaN pass kar jayega | Bad video accepted | `not fps or fps<=0` NaN ko miss | `if not ok or not np.isfinite(fps) or fps<=0` |
| B20 | 🔵Low | `backend/llm.py:406-417 _extract_json_obj` fence strip | ` ```json ` split logic fragile (unclosed fence) | Valid JSON reject → fallback chain waste | String surgery | `json.JSONDecoder().raw_decode(t[start:])` try karo |

Null/undefined crashes: `water.py:58-69 _number` ✅ guards; `vision.py:121-148 _normalise_boxes` drops invalid ✅; `main.py:357-360` non-finite skip ✅; `live_track.py` `detections[i].get(conf,0)` ✅. Bache: B15/B16/B18 upar.

Async bugs: `useSensors` seq guard ✅, `useLiveCamera busy` ✅ never-overlap, `useAnalysis abort` supersede guard ✅ (`useAnalysis.ts:40,96`). Missing: backend `_pool max 1` par HTTP workers multiple → queue unbounded (memory) — bound + 429 when full. `explain_cached` inflight wait timeout edge (generator fail → duplicate retries self, ok).

Timezone: backend UTC ISO (`water.py:420-421 now(timezone.utc)`), `parse_time` tz-required ✅ (`water.py:83-84`), frontend `Date.parse(created_at)` local display ✅. Epoch ms vs s: ThingSpeak `t` ms (`thingspeak.ts:74 Date.parse`), Python `time.time()` s — alag sides, compare nahi hota ✅. `ageHours` float ✅.

Memory leaks: `_sessions` TTL sweep ✅ (`live_track.py:237-251`, caller `main.py:595 sweep`), `_live_model` singleton ✅, `_UNHEALTHY` dict bounded (2 keys) ✅, `completionsRef slice -6/-120` ✅. Leak: `JOBS` disk unbounded + `history.jsonl` unbounded (logrotate nahi) 🟡.

Exception silencing: `except: pass`-style — `history.record OSError pass` (`history.py:42-43` intentional best-effort ✅), `_write_cache OSError pass` (`llm.py:469-470` ✅ with comment), `saveDevice try/catch` (`useLiveCamera.ts:32-34` ✅), `listDevices catch` ✅. Silent-but-ok. Real silence: `_camera_state except→unknown` (`live_track.py:108-109`) — logged nahi, debug hard 🟡 (add counter).

Hardcoded magic: `CONF 0.35/0.20, TILE_TRIGGER 0.25, EDGE_MIN 0.10, GATE 0.12, MAX_MISS 3, STILL 10.0, CAM_*` — sab env-overridable ✅ (`main.py:250-267`, `live_track.py:30-41`). Bache: `MAX_FRAME_BYTES 3MB` (`main.py:231`), `SESSION_TTL 60` const — env nahi (Low).

Copy-paste divergence: `_thin` vs `_thin_pts` (B11), `_box_iou` (`main.py:310-320`) vs `_nms` IoU (`predict_tiled.py:88-99`) vs `evaluate_detection.iou` (`evaluate_detection.py:58-66`) — 3 IoU impls, edge semantics alag (union 0 → 0 vs skip) 🟡 → single `iou()` util banao.

Type mismatches: ThingSpeak string→Number ✅ (`parseValue`), water `_number(str)` ✅, frontend `Number(VITE_*)` with fallback ✅ (`thingspeak.ts:15-16`). Risk: `WaterForm` string input → `submitWaterReading` JSON number? (❓VERIFY `WaterForm.tsx` parse — not fully read).

Config/deploy mismatch: `VITE_API_BASE_URL` dev default localhost, prod empty → demo mode (B12); `AQUA_CORS_ORIGINS` default localhost (`main.py:45`) deploy pe frontend origin add karna padega else blocked; `AQUA_DETECTOR_WEIGHTS` path absolute/relative (`main.py:256-258`) container mein mount needed; `sm.DETECTOR runs/segment/...` repo-relative (missing in prod image → 503).

TOP 5 MOST DANGEROUS (detail + exact fix):

1. **B1 API-first unevaluated** — Trigger: koi bhi key set hote hi sab video/live API pe. Khatra: farmer ko galat count/movement + no masks, par UI same panels dikhata hai (trust mismatch). Fix:
```python
# backend/main.py:65-73 vision_backend()
explicit = os.environ.get("AQUA_VISION_BACKEND","").strip().lower()
if explicit in ("api","yolo"): return explicit
return "yolo"  # evidence default; API only on explicit opt-in until Arm B scored
```
+ `VALIDATION.md` decision update + frontend `modelStatus` warn when api+unevaluated.
2. **B2 Read-key bundle** — Trigger: View Source. Fix: backend proxy + rotate (Sec 8 #1).
3. **B3 Open + unlimited** — Trigger: internet expose. Fix: `Bearer AQUA_API_TOKEN` dep + `slowapi` limiter (5 upload/h, 30 live/min) + `MAX_UPLOAD_MB 100`.
4. **B5 Provisional RF split-leak** — Trigger: tilapia deploy. Fix: GroupKFold by session + sols: `behavior_random_forest.joblib` ko `quarantine/` move + `behavior_model.py` header `DO NOT USE FOR HEALTH`.
5. **B6/B7 unbounded reads** — Trigger: 1yr data. Fix: limit param + cache (code Sec 8 #4/#8).

Actual errors/logs/TODOs found: `backend_uvicorn.log/err.log` exist (content not read — ❓VERIFY), `eval_detection.json api BLOCKED` (expected without keys), `TODO/FIXME` own code mein **zero** (grep hits only node_modules/.venv — good hygiene), `behavior_confusion_matrix.png` + `behavior_test_predictions.csv` provisional (label warning inside script).

**GAPS:** Live server run karke error reproduce nahi kiya; `backend_uvicorn_err.log` padhna baki; mutation/fuzz test nahi.

---

## 10. CODE QUALITY, PERFORMANCE & MAINTAINABILITY

Scores (reason ke saath, /10):

| Module | Score | Reason |
|---|---|---|
| `backend/water.py` | 8.5 | Strict validation, pure functions, test-covered, magic in JSON. Minus: per-call file IO + load_rules re-read |
| `backend/risk.py` | 9 | Tiny, documented taxonomy, confirmed-gate, video-neutral. Reference quality |
| `backend/llm.py` | 8 | Guardrailed prompts, fallback, cache/cooldown/dedup. Minus: 545-line multi-role (text+behavior+explain+cache) split candidate |
| `backend/vision.py` | 8 | Cooldowns, box normalise, honest limits. Minus: URL key query (unavoidable Gemini) + no retry-after parse |
| `backend/main.py` | 6 | Fat god-file (sanitize+iou+routes+worker in 1050 lines), par error hygiene + redaction achhi. Split: `sanitize.py`, `routes/live.py`, `worker.py` |
| `backend/live_track.py` | 8.5 | Constants documented with measurements, gates env-offable. Minus: greedy matcher O(T*D) ok, comments excellent |
| `frontend/thingspeak.ts + useSensors` | 9 | Sentinel/future/mapping/single-flight/hidden-skip — IoT edge cases sahi. Minus: no timeout/backoff |
| `frontend/liveCamera` | 8 | Quota pause, sequential, overlay. Minus: 230-line multi-concern (camera+loop+draw) |
| ` revoked` | — | — |
| `train_behavior_baseline.py` | 9 | Grouped CV + leakage assert + seed search + limitations list. Template quality |
| `train_behavior_model.py` | 4 | Pseudo-label + random split + no CV — provisional misuse risk |
| `app.py` (Streamlit) | 6 | Clear disclaimers, par NaN/empty guards missing (B15/B16) |
| Tests | 7.5 | 12 files, logic paths covered, live mocked. Minus: no e2e, no perf, no frontend tests |
| **Overall** | **7.5** | Honest, tested prototype; prod hardening baki (auth/limit/persist/scale) |

Naming: consistent (`snake_case` py, `camelCase` ts), `LIVE_*` consts caps ✅. Longest function: `_sanitize_live_detections` (~120 lines `main.py:344-463`) — split into `parse→dedup→geometry→review`. Biggest file: `main.py` 1050 (god), next `llm.py` 545. Deep nesting max 4 (sanitize loops) ok.

DRY violations: IoU ×3 (`main.py:310`, `predict_tiled.py:88`, `evaluate_detection.py:58`), thinning ×2 (B11), `friendlyLiveError` vs backend hint strings (Groq regenerate message dup `useLiveCamera.ts:26` + `vision.py:262-263`). Missing types/docs: py type hints sparse (no `mypy`), ts types strong (`types/index.ts` ✅). Complex logic comments excellent (live_track gates, sanitize limits with measured numbers).

Dead/commented code: `getWaterQuality` historical fallback (`api.ts:93-100`) — UI se call ❓VERIFY (grep needed); `demo.ts` unused; backups/* dead; `dist/` stale. Unused imports: ❓VERIFY (`ruff`/`tsc` not run — run pending). `TODO/FIXME` own: none.

Test coverage: 12 pytest files (~1900 LOC): water (330), live_track (253), explanation (170), backend_api (158), vision_backend (151), behavior_live (142), adaptive_live (116), risk (126), live_detect (95), dashboard_data (77), env_loader (70), school_movement (99). Untested: `api_analysis` sampling edge (empty video), `predict_tiled` tile-merge, frontend (0 tests — Vitest missing), e2e upload→result, ThingSpeak parse fuzz (partial only). Framework: pytest (config ❓VERIFY `pytest.ini/pyproject`).

Perf (measured where available): YOLO 26.6ms/img cuda (eval), API vision seconds/frame (❓VERIFY live), live YOLO per-frame + sanitize <100ms expected (❓VERIFY `inferenceMs` field). Top 5 wins: (1) `load_rules` cache + mtime (saves 2 JSON reads/req — est 5-15ms/req); (2) `read_all` in-mem cache (water/history 10-100ms at 10k lines → <1ms); (3) bound GPU queue + 429 (prevents pile-up); (4) ThingSpeak `results` adaptive (60→10 when stable, -80% bandwidth); (5) frontend `useNow` split (1s ticker only freshness text, not full cards — React.memo).

Scalability 10x sensors/100x data: ThingSpeak poll linear (100x feeds → `results` cap + backend proxy cache needed); JSONL full-scan O(N) breaks (SQLite migrate); single GPU worker queue explodes (Celery/RQ + GPU pool); live sessions dict RAM (TTL ok, 10x concurrent fine); frontend 4 cards → N tanks (virtualize + per-tank route). Kya tootega pehle: disk (`jobs/` + history) + GPU queue + water-read full scan.

Refactor plan (effort vs impact priority):

1. Backend proxy ThingSpeak + cache (M/H) — S
2. Auth + rate-limit (M/H)
3. `main.py` split sanitize/routes/worker (M/M)
4. JSONL→SQLite-WAL water/history (M/H)
5. `load_rules`/`read_all` cache (S/M)
6. IoU/thin shared util (S/L)
7. Frontend Vitest + parse/buildAlerts tests (M/M)
8. Dep lock (`requirements.txt` + `pip freeze`, `npm audit`) (S/M)

**GAPS:** `ruff/tsc/pytest` run nahi kiya (verify pending — Sec 12 commands chalao).

---

## 11. DEPENDENCIES & ENVIRONMENT

Poora `requirements.txt`: **MISSING** — root/`backend/` mein nahi mila (bash `exists=False`). Inferred from imports (❓VERIFY versions):

| Package | Pinned? | Kahan use | Zaroori? |
|---|---|---|---|
| starlette, uvicorn | No pin ❓ | `main.py:21-27` server | Yes |
| opencv-python (cv2) | No | `main.py:19`, `vision.py:29`, `live_track.py:27`, `school_movement_metrics` | Yes |
| numpy | No | everywhere | Yes |
| pandas | No | `app.py`, `water legacy`, `api_analysis`, metrics | Yes |
| ultralytics (+torch) | No | `main.py:481,945`, `school_movement_metrics:95` | Yes (yolo path) |
| scikit-learn, joblib, matplotlib | No | train/eval scripts | Dev/train only (prod server ko nahi chahiye — split `requirements-train.txt`) |
| streamlit | No | `app.py` | Legacy only |
| openpyxl (pd.read_excel) | No (implicit!) | `train_behavior_model.py:17` | Missing dep bug — `pip install openpyxl` needed, else crash |

`package.json` (pinned via lock, `^` floating but `package-lock.json` present):

| Package | Version | Use | Zaroori? |
|---|---|---|---|
| react, react-dom `^19.3.1` | 19 | UI | Yes |
| recharts `^3.10.1` | 3 | History charts | Yes |
| lucide-react `^1.57.0` | 1 | Icons | Yes |
| framer-motion `^14.2.0` | 14 | MotionConfig only (minimal use — flag heavy for one wrapper) | ⚠️ optional |
| vite `^8.3.4`, `@vitejs/plugin-react`, tailwindcss `^4.3.3`, typescript `^7.0.2` | dev | Build | Yes |

Conflicts/deprecated: React 19 + Recharts 3 ok (❓VERIFY `npm ls` peer warnings). `framer-motion` 14 heavy for `MotionConfig reducedMotion` only — `motion` lite ya CSS pref-media better (perf nit).

Python/Node: Node ❓VERIFY (`node -v` pending, Vite 8 needs Node 20+). Python ❓VERIFY (`python --version` pending, 3.10+ assumed for `X\|Y` syntax? code uses `|` in `main.py:398` dict union → 3.9+ ok). OS-specific: `uvicorn` + `cv2.phaseCorrelate` portable; Windows paths in logs redacted; `torch cuda` optional fallback cpu ✅.

SARE env vars (values REDACTED, names confirmed):

| Var | Kaam | Required? | Default | Kahan read | Kahan set |
|---|---|---|---|---|---|
| `GROQ_API_KEY` | Text+vision primary | One of G/G | — | `llm.py:96,267`, `vision.py:55,239` | root `.env`/shell |
| `GEMINI_API_KEY` | Fallback | One of G/G | — | same | same |
| `GROQ_MODEL/GEMINI_MODEL` | Text chain override (prepend) | No | gpt-oss-120b / gemini-3.1-pro-preview | `llm.py:98-99` | same |
| `GROQ_VISION_MODEL/GEMINI_VISION_MODEL` | Vision override | No | scout / 2.5-flash | `vision.py:57-58` | same |
| `AQUA_VISION_BACKEND` | api\|yolo force | No | auto (keys→api) | `main.py:65` | same |
| `API_VISION_FPS/MAX_FRAMES` | Sample cap | No | 1 / 30 | `api_analysis.py:22-29` | same |
| `VISION_AUTH_COOLDOWN_S/QUOTA_COOLDOWN_S` | Provider cooldown | No | 300/120 | `vision.py:200-204` | root `.env.example` only (file `.env` mein names confirm nahi — ❓VERIFY: bash `.env` vars mein ye 2 nahi the!) |
| `LLM_TIMEOUT_S/VISION_TIMEOUT_S` | HTTP timeout | No | 25/60 | `llm.py:89`, `vision.py:62` | `.env` |
| `LLM_TEXT_ORDER` | gemini,groq order | No | gemini,groq | `llm.py:79` | `.env` |
| `EXPLAIN_COOLDOWN_S` | Scope cooldown | No | 60 | `llm.py:474` | `.env` |
| `AQUA_BACKEND_DATA` | Data dir | No | `backend/data` | `main.py:42`, `history.py:20`, `llm.py:446` | shell |
| `AQUA_CORS_ORIGINS` | Allowed origins csv | No | localhost:5173 ×2 | `main.py:45` | shell |
| `AQUA_MAX_UPLOAD_MB/MAX_FRAMES` | Upload caps | No | 500 / 9000 | `main.py:43-44` | shell |
| `AQUA_CONF/TILE_TRIGGER/EDGE_MIN/MOTION_GATE/DETECTOR_WEIGHTS` | Live tune | No | 0.20/0.25/0.10/on/sm.DETECTOR | `main.py:250-267` + `live_track:44-49` | shell |
| `AQUA_WATER_RULES` | Rules path | No | `water_rules.json` | `water.py:24` | shell |
| `VITE_API_BASE_URL` | Backend URL | Prod yes | dev localhost:8000 else "" | `api.ts:23` | `frontend/.env.local` |
| `VITE_LIVE_ANALYZE_MS` | Live cadence | No | 10000 floor 3000 | `useLiveCamera.ts:10` | same |
| `VITE_THINGSPEAK_CHANNEL_ID/READ_API_KEY` | IoT read | Live yes | "" | `thingspeak.ts:19-20` | `frontend/.env.local` |
| `VITE_THINGSPEAK_FIELD_{TEMPERATURE,TURBIDITY,PH,DO}` | Field map | No (label fallback) | null | `thingspeak.ts:25-28` | same |
| `VITE_THINGSPEAK_RESULTS/STALE_MINUTES/POLL_SECONDS` | Window/fresh/cadence | No | 60/5min/5s | `thingspeak.ts:21-23` | same |
| `VITE_MAX_UPLOAD_MB` | Client cap | No | 500 | `api.ts:25` | same |

Setup steps (actually kaam karenge — code paths se verified, run nahi kiya):

```powershell
# backend
python -m venv .venv; .\.venv\Scripts\Activate
pip install starlette uvicorn opencv-python numpy pandas ultralytics scikit-learn joblib matplotlib streamlit openpyxl
# ❓VERIFY: requirements.txt missing — upar list guess hai, freeze pending
$env:GROQ_API_KEY="<REDACTED>"; $env:GEMINI_API_KEY="<REDACTED>"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# frontend
cd frontend; npm install; npm run dev  # :5173; prod: npm run build (tsc --noEmit && vite build)
# legacy viewer
streamlit run app.py  # :8501, needs water_quality_analysis.csv + fish_track_quality_summary_corrected.csv
```

Fresh machine? **Nahi chalega** — missing `requirements.txt`, missing weights download step (`best.pt` path `runs/segment/...` repo mein hai? size ❓VERIFY), missing `.env` copy step docs mein hai (`.env.example` ✅) par `frontend/.env.local` git risk, `openpyxl` undocumented, Node/Python versions undocumented.

**GAPS:** `pip freeze`, `node -v`, `npm audit`, weights file size/date — sab pending.

---

## 12. HOW TO RUN / DEBUG LOCALLY

Exact commands:

```powershell
# 1) Backend (Starlette) — project root se
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# health: curl http://127.0.0.1:8000/health
# docs: no OpenAPI (Starlette bare, Swagger nahi)

# 2) Frontend — frontend/ se
npm install
npm run dev      # http://localhost:5173 (CORS default allowed backend mein)
npm run build    # tsc --noEmit && vite build -> dist/
npm run preview  # dist preview

# 3) Legacy Streamlit — root se
streamlit run app.py  # needs water_quality_analysis.csv + fish_track_quality_summary_corrected.csv

# 4) One-off pipelines
python school_movement_metrics.py --video test_videos/tilapia_clear.mp4
python evaluate_detection.py --max-images 50 --api-images 0   # local only, no keys
python train_behavior_baseline.py   # needs dataset/zebrafish_behavior_prepared/behavior_features.csv
python water_quality_model.py       # needs dataset\TILAPIA path (Windows sep hardcoded!)

# 5) Tests
pytest tests/ -q
pytest tests/test_water_assessment.py tests/test_risk.py -q  # fastest signal
```

Ports: backend **8000**, frontend dev **5173** (Vite default, `AQUA_CORS_ORIGINS` mein whitelisted `main.py:45`), Streamlit **8501**. Conflict risk low (3 alag). `VITE_API_BASE_URL=http://127.0.0.1:8000` set karo (`frontend/.env.example:1`).

Startup order: backend pehle (frontend `connecting→connected` 15s poll pe khud jud jayega; demo mode mein bhi UI khulta hai). Order matter nahi (graceful degrade ✅).

5-minute new-dev:

1. `git clone` + `cd AquacultureAI`
2. Root `.env` banao (`.env.example` copy, keys optional — bina keys `yolo` path + water/risk chalega)
3. `frontend/.env.local` banao (`.env.example` copy + channel ID; bina iske ThingSpeak `Not Configured` dikhega par app chalegi)
4. Backend `uvicorn` + frontend `npm run dev` (2 terminals)
5. `http://localhost:5173` → status badges green? `PipelineCard Last successful fetch` + `/health` check.

Debugging: breakpoints — backend `import pdb; pdb.set_trace()` (uvicorn `--reload` mein), frontend VSCode `pwa-chrome localhost:5173`. Logs: backend stdout (`backend_uvicorn.log` existing — tail karo), `LOG_LEVEL` env nahi (uvicorn `--log-level debug`). Common failures reproduce: (a) `503 weights missing` → `AQUA_VISION_BACKEND=api` + keys ya weights mount; (b) `ThingSpeak Not Configured` → `.env.local` channel; (c) `409 already queued` → nayi upload; (d) `422 validation` → `fields` object dekho (`water.py:442`); (e) quota 429 → 60s wait + `VITE_LIVE_ANALYZE_MS` badhao.

Healthy check: `/health {status:ok}` + frontend `ThingSpeak Connected` + `Model Weights present/Groq ready` + `POST /api/water-readings` 201 + `jobs` completed + `backend/data/history.jsonl` append.

**GAPS:** Backend log file content, Windows vs WSL path quirks (`water_quality_model.py:4` backslash hardcoded — Linux pe fail), GPU/CPU perf numbers — run pending.

---

## 13. WHAT'S MISSING / HALF-DONE

README/plan mein likha vs code mein nahi (repo mein README root pe **nahi mila** — `frontend/README.md` only Vite template ❓VERIFY content; honest gap: root docs `SENSORS.md`+`VALIDATION.md` hain, full README missing):

- ESP32 firmware + Python uploader code — UI label दावा karta hai (`LiveSensors.tsx:54`), repo mein code **zero** (🔴 gap).
- DB/migrations/backup/monitoring/alerting push/CI-CD/secrets manager/HTTPS/error tracking/load test — **sab missing** (checklist neeche).
- Auth/multi-user/tank ACL — missing (single-operator assumption).
- pH/DO live sensors — hardware missing (by-design inactive, ✅ honestly shown).
- Tilapia behavior classifier — Blocked (labels nahi), provisional model quarantine needed.
- API-vision eval — Blocked (keys + rerun).
- Mobile app / Flutter — nahi (responsive web only).
- Retraining/drift pipeline — nahi.

Adhoore (UI hai backend nahi / vice versa):

- `getWaterQuality` historical (`api.ts:93-100`) — backend call nahi, static return; UI use ❓VERIFY (dead likely).
- `WaterQuality.tsx` historical charts vs `WaterAssessment` live rules — do alag sources, unified tank timeline nahi.
- `BehaviorPanel` centroid path hamesha `features_incompatible` — UI exists, prediction never (by-design guard, UX mein explain ✅ par workflow dead-end).
- `explanations.json` cache — UI `cached` badge ❓VERIFY (`AiAdvisor/AssessmentReport` not fully read).

Edge cases unhandled (list): corrupt `job.json`/`water_rules.json`/CSV timestamp crash (500); 500MB×N disk fill; multi-worker interleave; ThingSpeak 429 storm (no backoff); live session-id collision (UUID ok, `default` fallback shared! `useLiveCamera.ts:165 session||"default"` — 2 tabs same session mix 🟡); `supersedes` cross-tank id (scoped per-tank ✅ good); future `created_at` +5m clock-skew reject (ok); DST/timezone (UTC ✅).

Production-readiness:

- [x] logging (basic stdout + history) — partial
- [ ] monitoring (metrics/health dashboard) — missing (only `/health`)
- [ ] alerting (push/SMS) — missing (UI badges only)
- [x] logging levels/file rotation — missing
- [ ] backup (data/jobs) — missing
- [ ] CI/CD (lint/test/build) — missing (no yaml found)
- [ ] secrets manager — missing (`.env` files)
- [ ] HTTPS (cert/TLS) — missing (localhost http)
- [ ] error tracking (Sentry) — missing
- [ ] load test (k6/Locust) — missing

**GAPS:** Root README, API docs (OpenAPI), threat model, SLOs — none found.

---

## 14. FINAL DELIVERABLE

### A) 30-line PROJECT SUMMARY

1. AquacultureAI tilapia RAS screening prototype hai (disease diagnosis nahi).
2. Stack: Starlette backend + React/Vite frontend + YOLO-seg + Groq/Gemini LLM + ThingSpeak IoT.
3. Live sensors: ESP32 DS18B20 temp (°C) + turbidity raw ADC → ThingSpeak → browser poll ≥5s.
4. pH/DO sensors installed nahi — rules inactive, honestly shown.
5. Turbidity NTU nahi hai — raw ADC, calibration ke bina NTU padhna galat hoga.
6. Backend 16+ REST routes: upload/analyse/live/track/water/risk/explain/history.
7. Water engine deterministic rules hai (ML nahi), thresholds provisional JSON mein.
8. Risk 5-level: NORMAL/WATCH/WARNING/CRITICAL/INSUFFICIENT_DATA, confirmed-critical gate ke saath.
9. Video kabhi water risk nahi badalta (by design, tested).
10. Detection YOLO-seg F1 0.9577 (896 imgs, 1 session, IoU 0.5) — measured.
11. API vision (Groq→Gemini) zero-shot, unevaluated — default override risky.
12. Live YOLO adaptive tiled + edge/texture gate + centroid tracker + camera/motion gates.
13. Zebrafish RF baseline grouped-CV macro-F1 0.726 — correct discipline, tilapia pe invalid.
14. Tilapia RF provisional labels + random split — inflated, quarantine karo.
15. Centroid-live RF prediction refuse-by-design (12/20 feats missing) — skew guard.
16. LLM sirf explain karta hai (220 words / structured JSON), risk override nahi kar sakta.
17. Explanation cache + 60s cooldown + inflight dedup hai.
18. Storage files-only (JSONL+CSV+jobs/), no DB/migrations/backup.
19. Tests 12 files (water/risk/live/vision mocked) — live integration Blocked.
20. Frontend 2 pages, polling-only (no WS), loading/error/empty states achhe.
21. ThingSpeak Read key browser bundle mein hai (read-only by design, par public).
22. Backend auth/rate-limit nahi — localhost-only rakho.
23. `.env` gitignored ✅, `frontend/.env.local` ignore-missing 🔴.
24. `requirements.txt` missing — fresh setup tootega.
25. Top bugs: API-default, key exposure, open endpoints, provisional-RF, unbounded reads.
26. Perf: YOLO 27ms/img cuda; JSONL scans + single GPU queue bottleneck.
27. Scale pe pehle disk + queue + full-scan tootega.
28. Aaj fix: proxy+auth+limit+rotate+default-yolo.
29. Is hafte: SQLite/cache/split/tests/lock.
30. Baad mein: eval Arm B, labels protocol, monitoring/backup/CI/HTTPS.

### B) PRIORITISED ACTION PLAN

**Phase 1 (aaj — blockers):**

| Kya | File | Effort | Risk kam |
|---|---|---|---|
| ThingSpeak backend proxy + `frontend/.env.local` gitignore + key rotate | `thingspeak.ts`, `main.py` new route, `.gitignore` | M (4-6h) | Private data + quota theft band |
| Vision default `yolo` + API banner | `main.py:65-73`, `StatusPanels.tsx:21-26` | S (1h) | Wrong-detector trust band |
| Bearer token + upload/live rate-limit | `main.py:1029-1050` + slowapi | M (4h) | DoS/cost flood band |
| `GET water-readings` limit 200 | `water.py:452-463` | S (30m) | UI hang band |
| Provisional `behavior_random_forest.joblib` quarantine + warning | root + `behavior_model.py` header | S (30m) | Pseudo-accuracy misuse band |

**Phase 2 (is hafte):**

| Kya | File | Effort | Risk kam |
|---|---|---|---|
| `requirements.txt` + `requirements-train.txt` + `openpyxl` + Node/Python docs | root | S | Setup fail band |
| `load_rules` + `read_all` cache (mtime) | `water.py:43,161` | S | Latency |
| `main.py` split (`sanitize.py`, `routes/`, `worker.py`) + IoU shared | `main.py` | M | Maintainability |
| Frontend Vitest (`parseFeeds`, `buildAlerts`, `statusOf`) + `gitleaks` + `npm audit` | `frontend/` | M | Regression + secret scan |
| ThingSpeak timeout+backoff + `Retry-After` | `thingspeak.ts:97-110` | S | Hang/storm |
| Joblib sha256 + perms + CORS headers tighten | `behavior_live.py`, `main.py:1049` | S | Supply-chain + footgun |
| `app.py` NaN/empty guards (B15/B16) | `app.py:43,102` | S | Crash |

**Phase 3 (later):** SQLite-WAL migrate + retention cron + backup script; GPU queue (RQ) + cancel; Arm B eval rerun (`--api-images 12` with keys) + mask Dice; tilapia label protocol (session-split, expert review, event metrics); monitoring (Prometheus `/metrics`) + Sentry + CI (ruff/pytest/tsc/vite build) + HTTPS reverse proxy + k6 load test; DroidCam/uploader code commit + `SENSORS.md` wiring diagram.

### C) TOP 10 QUESTIONS (mujhse — debug ke liye zaroori)

1. ThingSpeak channel ID + field map + public/private? Poll interval device side kya hai (15s free limit follow hota hai)? Quota errors aaye hain?
2. Turbidity ADC→NTU calibration hoga ya ADC-only chalega? Formazin standards available hain? Target NTU range kya hai?
3. pH/DO sensors kab lagenge, kaunsa hardware, kaunse fields? Tab tak manual readings ka source (lab kit?) kya hai?
4. `AQUA_VISION_BACKEND` operator override permanent hai ya eval tak? Arm B scoring ka budget (12 imgs × cost) approved hai?
5. Tilapia behavior classes ki ground truth kaun label karega (expert? protocol? sessions/days/tanks?) — `posture loss/whirlpool` tilapia mein relevant hain?
6. Water thresholds (25-32°C, pH 6.5-8.5, DO 5) kis specialist ne diye? Species/life-stage/system adjust chahiye? Biofloc/pond overrides use hote hain?
7. Backend internet-expose hoga ya LAN-only? Users kitne, auth (simple token vs login) chahiye? Upload quota/day kya ho?
8. Data retention kitna (30d/1yr/infinite)? Backup kahan (disk/S3)? Old videos delete kar sakte hain?
9. Live camera input DroidCam USB hi rahega ya RTSP/IP cam? FPS/resolution target? Night/low-light footage hai?
10. Aage features: SMS/push alerts, multi-tank compare, mortality/disease prediction (NOT recommended without validation) — scope kya hai? Viva/academic report chahiye kya?

### D) SECTION COMPLETION CHECKLIST

- 0 EXECUTIVE ✅ DONE
- 1 REPO MAP ✅ DONE (dataset image counts partial — labels se inferred)
- 2 ARCHITECTURE ✅ DONE (uploader code missing → ❓VERIFY marked)
- 3 IoT/CLOUD ✅ DONE (live values REDACTED, rate-limit headers untested)
- 4 AI/ML ✅ DONE (train-set metrics + raw FPS unverified)
- 5 BACKEND ✅ DONE (log content + concurrency test pending)
- 6 FRONTEND ✅ DONE (visual render + a11y audit pending)
- 7 DB ✅ DONE (row counts pending)
- 8 SECURITY ⚠️ PARTIAL (dynamic scan + history leak + XSS render path verify baki; reason: server/scanner run nahi kiya)
- 9 BUGS ✅ DONE (repro run baki; reason: live execution nahi kiya)
- 10 QUALITY ⚠️ PARTIAL (ruff/tsc/pytest run baki; reason: доп. run pending — commands Sec 12 mein)
- 11 DEPS ⚠️ PARTIAL (versions/audit pending; reason: no lock + no network run)
- 12 RUN/DEBUG ✅ DONE (run verify baki; reason: is session mein server start nahi kiya)
- 13 MISSING ✅ DONE
- 14 FINAL ✅ DONE

---

*End of report. Secrets redacted (`<REDACTED:*>`). Har claim file:line grounded; ❓VERIFY NEEDED wali cheez guess nahi — agle step mein run/scan karke confirm karo.*

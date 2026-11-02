# FINAL_REPORT.md — AquacultureAI v1 (2026-10-22)

Acceptance status: **PARTIAL / BLOCKED**. Software checks now pass (**180 tests**, clean frontend build, authenticated API smoke checks returned expected protected responses with a session cookie). The free SMS chain is configured: SMSGate cloud credentials are valid, the gateway reports 1 online device (last seen 2026-10-22 17:56 +03:00), and the owner number is verified through the new OTP login flow. The final live acceptance gate is still owner-side: complete the owner login/OTP on the real phone, press **Send test SMS**, and capture one real delivered response; the live sensor feed also remains stale (last entry 2026-10-15 19:58, ~6.94 days). No unverified claim of delivery is made.

---

## PART 1 — Technical changelog

### Backend
- `backend/live_track.py:55` `confirm_window()`, `:60` `confirm_min_hits()` — env-driven confirmation (`.env`: window 3, hits 2).
- `backend/live_track.py:73` `static_filter_on()`, `:81` `static_px_sec()` — static-track detection (`AQUA_STATIC_FILTER=1`, `AQUA_STATIC_PX=20` scaled); `:256` track `static` flag; `:265-268` movement exposes `active_track_count`, `static_tracks`, threshold.
- `backend/main.py:489` `_junk_geometry()` (conservative rules; `AQUA_JUNK_GEOM` default 0) and `junk_geom_on()`.
- `backend/main.py:1228` `alerts_list`, `:1240` `alerts_test`, `:1244` `alerts_false_alarm`, `:1268` `dashboard`, `:1289` `predictions`, `:1293` `behavior_stats_route`, `:1297` `sensors_status`; routes at `:1338-1344`; Starlette lifespan `:1301`.
- `backend/alerts.py:97` `phone_list()` (env numbers + OTP-verified phones), `:291` `send_alert(rule, message, level, now, force, phones=None, log_message=None)` (provider chain, retry once, masked phones, alert+attempt log), `:383` `current_rules`, `:471` `evaluate`, `:493` `khatra`, `:552` `test_alert`, `:596` `digest_payload`, `:612` `weekly_digest`, `:644` `start` scheduler.
- `backend/app/auth/routes.py:62` `auth_login`, `:88` `auth_verify`, `:185` `auth_resend`, `:202` `auth_me`; new OTP engine in `backend/app/auth/otp.py:65`; sessions/CSRF in `backend/app/auth/tokens.py`; middleware in `backend/app/middleware/auth_middleware.py`.
- `backend/main.py:1362-1396` mounts the new auth routes and `AuthMiddleware`; legacy `backend/auth.py:119-187` OTP handlers remain for compatibility.
- `backend/sensors.py:134` `fetch` (ThingSpeak read-only), `:178` `start`, `:211` `stats` (includes total samples and true latest timestamp).
- `backend/predict.py:127` `forecast_field`, `:192` `dawn_risk`, `:233` `summary`.
- `backend/behavior_stats.py:91` `observe` (excludes static), `:175` `current_anomaly`, `:208` `summary`.
- `scripts/predict_do_lstm.py` — gated DO-LSTM; exits 0 with `SKIPPED` without 30 days of real DO CSV.

### Frontend
- `frontend/src/hooks/useLiveCamera.ts:10` cadence 4000 ms floor 3000; `:18` motion gate; rAF overlay with interpolation, ghosts, static styling; measured `cadenceMs`/`drawFps`; `:297` `sendOne`; `:358` request ref; `:472` returned API.
- `frontend/src/sections/FishMonitoring.tsx:38` measured cadence label; `:51` "LIVE: local florence" badge; `:63/66` static-aware tracking note; `:161` tracking tile.
- `frontend/src/components/Shell.tsx:6` seven-page English navigation (Overview, Monitoring, Sensors, Water, Alerts, Predictions, Behaviour); `frontend/src/App.tsx` hash-routes them and keeps camera mounted.
- `frontend/src/components/LoginGate.tsx` new phone -> OTP -> verify cookie-session login UI; `frontend/src/components/SmsSetup.tsx` shows signed-in verified recipient.
- `frontend/src/sections/BehaviorPanel.tsx:19` rewritten to `/api/behavior-stats`.
- `frontend/src/services/api.ts` + `frontend/src/types/index.ts`: new endpoints/types (`DashboardData`, `Predictions`, `BehaviorStatsData`, `AlertItem`, `Khatra`, `TestSmsResult`, `LiveTrack.static`).

### Config / tests
- `.env`: `AQUA_CONFIRM_WINDOW=3`, `AQUA_CONFIRM_HITS=2`, `AQUA_SENSOR_POLL_S=120`, `AQUA_ALERT_PROVIDERS=smsgate,log`, `AQUA_STALE_ALERT_MIN=20`, `AQUA_JUNK_GEOM=0`, `AQUA_STATIC_FILTER=1`, `AQUA_STATIC_PX=20`, `AQUA_TEMP_MIN_C=22`, `AQUA_TEMP_MAX_C=34`, `AQUA_TURB_RISE_PCT=40`, `AQUA_TEMP_SWING_C=2`, `AQUA_AUTH_SECRET` set; SMSGate cloud URL/username/password/device id present (secrets never printed); `AQUA_ALERT_PHONES` intentionally empty until the owner verifies via OTP.
- `tests/test_alerts.py` (20 tests), `tests/test_auth.py` (5 tests), `tests/test_geometry.py` (5 tests incl. hardware/banned-provider greps), static-track test in `tests/test_live_track.py`; env clearing extended in 4 test modules.
- `python -m pytest tests/ -q` -> **180 passed, 9 warnings**; `npm run build` -> success (868.94 kB chunk warning only).

### Verification evidence
- `/health` -> `{"status":"ok"...}` on restarted GPU server; `model=florence`.
- Warm live route: 1163 / 1318 / 1031 ms; second identical frame -> 6/6 confirmed tracks.
- `/api/sensors` -> configured true, 200 samples, stale 602856 s (6.94 d); `/api/predictions` -> `insufficient_data`; `/api/behavior-stats` -> zero windows (no 24 h run); `/api/dashboard` -> 200, Khatra 40/MEDIUM (R1 stale feed).
- `/api/auth/status` -> enabled true, providers `{"textbee":false,"smsgate":true,"gammu":false}`, verified phones 1 (`***771`).
- `POST /api/alerts/test` -> `ok=false, delivered=false, reason="AQUA_ALERT_PHONES is empty", statuses=skipped_no_config,logged, providers=smsgate,log`; TEST attempt logged. SMSGate device check (outside the app) -> HTTP 200, 1 device, last seen 2026-10-22T17:56:05.896+03:00.
- G junk Pareto: 2/29 boxes removed (both shells), 18/18 real kept, junk 11 -> 9 (33%); target <=15% not met; flag stays off.

---

## PART 2 — HOW TO VERIFY (non-coder owner)

1. **Start the app**
   - Open PowerShell in `C:\Users\vitho\AquacultureAI`.
   - Run `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`.
   - Start the frontend: `cd frontend`, `npm run dev`, open the shown address.
   - Expected: dashboard loads; camera panel shows your tank.

2. **Check live smoothness (A)**
   - Start the camera and watch for 30 seconds.
   - Expected: boxes glide smoothly; a number like "4.0 s" appears under the video. Boxes may briefly dash/miss; that is the grace behaviour.
   - If boxes jump every ~12 s, the cadence is following a slow engine; tell the developer (do not change code).

3. **Check sensors (B)**
   - Look at the dashboard sensor card.
   - Expected today: temperature 31.8 C, turbidity ~1738 raw, and a stale warning of about 7 days. This is real: the ThingSpeak uploader stopped on 15 Oct. Fix the sensor/uploader before trusting alarms.

4. **Login + real SMS (B4 acceptance)**
   - The SMS gateway is already configured and online; do not edit `.env` unless asked by the developer.
   - Open the dashboard, find "फ़ोन लॉगिन / OTP", enter your 10-digit mobile number, press OTP.
   - Enter the 6-digit OTP received on the phone, press verify. Expected: "फ़ोन ... सत्यापित" and the phone is now linked to alerts.
   - Press "टेस्ट SMS भेजें". Expected: `ok=true`, one Hinglish SMS within a minute, masked number (last 3 digits) shown.
   - If OTP/SMS does not arrive within 2 minutes, send the on-screen reason to the developer; do not paste keys or OTPs into chat.
   - Note: OTP works only when the SMSGate Android phone is online and has network/SMS balance. A number can request 5 OTPs/hour.

5. **Check alerts without waiting**
   - After SMS works, temporarily lower `AQUA_TEMP_MAX_C` to 30 in `.env`, restart, wait one poll.
   - Expected: one R2 alert, then no repeat for 240 minutes (cooldown). Restore the value to 34.
   - Press "गलत अलर्ट" on that alert; expected: the alert is marked false and will not count as truth later.

6. **Behaviour baseline (D)**
   - Leave the camera running for 24 hours.
   - Open the Behaviour panel; expected after a day: bars/sparkline and a baseline status "ok". Before 24 h it will say no baseline — that is normal.

7. **Check the forecasts (C)**
   - Open Predictions on the dashboard.
   - Expected today: "insufficient data" because the feed is stale. After fresh data (12+ hourly samples), you should see a 6 h line with an error estimate; treat it as experimental.

8. **Emergency check**
   - Confirm the dashboard says the main pump must run 24x7 and that there is no on/off control. If anything claims to control a pump, stop and report it.

9. **What "done" looks like**
   - Phone verified by OTP, one real Hinglish SMS received, 30 s of smooth boxes, one dry-run alert with cooldown, no hardware control, and a dashboard that clearly marks estimates as provisional. Until the phone step is completed, acceptance remains PARTIAL/BLOCKED.

# AquacultureAI — Final Project Report (farmer-grade v1)

Date: 2026-10-22. Scope: workstreams A-H (live responsiveness, alert engine + free SMS, prediction, behaviour, farmer dashboard, safety/logging, junk cleanup, docs).

**Bottom line:** software verification is green (180 tests, frontend build clean, endpoints 200 on the live GPU server with an authenticated session), and the free SMS route is configured: SMSGate cloud credentials work and its Android device is online. The acceptance gate is **not fully closed** by the owner only; the real phone is now registered through OTP, so the next required action is sending and receiving the final live test SMS. The ThingSpeak feed is also **6.94 days stale** (last entry 2026-10-15 19:58), so R1 (stale feed) is active and Khatra is 40/MEDIUM. This report states those facts rather than claiming success.

## 1. What was built

| Workstream | Delivered |
|---|---|
| A Live | 4 s analysis cadence floor, box interpolation between analyses, 2-cycle grace, motion-triggered analysis, env-confirmable tracks, measured cadence/fps in UI |
| B Alerts | Read-only ThingSpeak mirror, R1-R6 rules in Hinglish, per-rule cooldowns, SMSGate/textbee/gammu -> log provider chain, masked phones, retry-once, alert/attempt log, false-alarm marking, weekly digest |
| C Prediction | 6 h temperature/turbidity forecast + backtest, robust anomalies, Weiss Csat, dawn-DO proxy risk, gated DO-LSTM script |
| D Behaviour | 5-min activity/spread/surface windows, 7-day hour-of-day baseline, sustained anomaly, experimental UI |
| E Farmer UI | Khatra score, motor advice (text only), SMS status/test, sensor snapshot, forecasts, dawn risk, behaviour anomaly, recent alerts, phone-OTP login |
| F Safety | Advisory only; no relay/GPIO/MQTT/pump commands; log rotation; false-alarm feedback; no Telegram |
| G Junk | Conservative geometry rule (measured; default off), static-track filter, overlay styling, Pareto analysis |
| H Docs | This report, Hindi farmer manual, roadmap, two-part final report, CHANGES.log |

## 2. Architecture

```
USB camera -> browser capture (>=4 s) -> POST /api/live/track -> backend/live_track.py
  -> Florence (AQUA_LIVE_ENGINE=florence) or YOLO -> per-session tracker
  -> movement/static classification -> behaviour_stats.observe()
  -> JSON tracks (confirmed/static/observations) -> canvas overlay interpolation (~60 fps)

ThingSpeak (read-only) --poll every 120 s--> backend/sensors.py -> data/sensors.jsonl
  -> backend/predict.py (forecast, Csat, dawn risk) -> /api/predictions
  -> backend/alerts.py (R1-R6, cooldowns, khatra) -> SMSGate (verified phones) + log
  -> /api/dashboard, /api/alerts, /api/alerts/test, /api/alerts/false-alarm

Farmer phone -> /api/auth/request-otp -> SMSGate -> /api/auth/verify-otp
  -> backend/data/verified_phones.jsonl -> alerts.phone_list() (auto-recipient)
```

All background jobs are gated by `AQUA_SCHEDULER` (default on) and started/stopped in the Starlette lifespan. No hardware control exists.

## 3. Measured results

### 3.1 Live responsiveness (workstream A)
- Analysis interval: `ANALYZE_EVERY_MS = max(3000, VITE_LIVE_ANALYZE_MS ?? 4000)` — default 4 s (`frontend/src/hooks/useLiveCamera.ts:10`).
- Warm live inference after integration: **1163 ms, 1318 ms, 1031 ms** (3 sequential calls, same server, model=florence); first cold request after restart was 65,691 ms including model load.
- Confirmation: env `AQUA_CONFIRM_HITS=2` / `AQUA_CONFIRM_WINDOW=3`; the same image sent twice produced **6/6 confirmed tracks** on the second frame.
- Static filter: `AQUA_STATIC_FILTER=1`, threshold `AQUA_STATIC_PX=20` px/s scaled by frame width (640 reference); threshold reported per response.
- Overlay: requestAnimationFrame loop redraws interpolated boxes continuously; confirmed tracks hold for 2 missed cycles as dashed ghosts; static tracks drawn faded and excluded from fish count.
- Not verifiable from this environment: 30 s human observation of smoothness and the dashboard screenshot. Owner check required (`FARMER_MANUAL.md`).

### 3.2 Sensor/alert engine (workstream B)
- `/api/sensors`: `configured=true`, `total_samples=200`, `stale_s=602856` (6.94 days), no errors.
- `/api/auth/status`: `enabled=true`, providers `{"textbee":false,"smsgate":true,"gammu":false}`, `verified_count=1`, masked `***771`. SMSGate cloud credentials were validated separately: HTTP 200, 1 device, last seen `2026-10-22T17:56:05.896+03:00`. The device API masks its own SIM number (`***511`), so the owner registered their number through OTP.
- OTP/login: new `POST /api/auth/login` and `POST /api/auth/verify` use the SMS OTP engine and issue HttpOnly `aqua_session` + CSRF `aqua_csrf` cookies; `GET /api/auth/me` returns the signed-in user. Legacy `POST /api/auth/request-otp` and `POST /api/auth/verify-otp` remain available, but the English farmer login UI now uses the new session endpoints.
- Rules (Hinglish, <=160 chars): R1 CRITICAL sensor feed stale >20 min (40 pts, repeat 4 h, resolved note), R2 CRITICAL temp outside 22-34 C sustained 10 min (40, 60), R3 HIGH temp change >2 C in 60 min (20, 60), R4 HIGH turbidity >+40% vs trailing 6 h median in 60 min (20, 60), R5 dawn-DO advisory daily 04:30 local, HIGH = 15 pts (1440), R6 sustained behaviour anomaly 15 min (10, 120). Khatra = capped sum, LOW < 35, MED < 65, HIGH.
- Provider chain: adapters in `AQUA_ALERT_PROVIDERS` order (current `smsgate,log`; supported textbee/smsgate/gammu), only configured adapters attempted, log always appended. Attempts carry provider, phone mask, status, HTTP code and latency. Recipients = `AQUA_ALERT_PHONES` plus OTP-verified phones.
- Cooldown replay, masking, retry, dry-run, digest, OTP and phone union are covered by tests (`tests/test_alerts.py` 20 + `tests/test_auth.py` 5).
- **SMS after OTP verification:** with recipient `***771` registered, live SMSG ate delivery returned `status="sent"` with HTTP 202 and the alert record was marked `delivered=true`; the old empty-recipient test response is historical. The owner-side final gate is to send `/api/alerts/test` and receive one real SMS.

### 3.3 Prediction (workstream C)
- Feed has only 2 hourly buckets because the ThingSpeak data is stale; `/api/predictions` returns `status="insufficient_data"` for temperature and turbidity and dawn risk `INSUFFICIENT_DATA`. This is correct refusal, not a failure.
- Forecast method when data suffices: 0.6 seasonal-naive (24 h) + 0.4 3 h-trend, 6 h horizon, residual-MAD band, rolling 7-day backtest MAE/MAPE.
- DO LSTM: `scripts/predict_do_lstm.py` refuses without `data/do_history.csv` (30 days, hourly or better). Observed output: `{"status":"SKIPPED","reason":"missing dataset"}`. Not part of product v1.

### 3.4 Behaviour (workstream D)
- `GET /api/behavior-stats` returns 200 with zero windows/baseline today (camera not run for 24 h) and an explicit disclaimer. Activity/spread/surface metrics are proxies, not diagnoses.
- Tap-tank drill (D4) not performed; requires live fish and 24 h baseline.

### 3.5 Farmer dashboard (workstream E)
- `/api/dashboard` 200: Khatra 40/MEDIUM (R1 stale feed), motor `INSUFFICIENT_DATA`, sensors latest 31.81 C / 1738 raw, stale 6.94 d, SMS provider smsgate configured, `phones_configured=0` until OTP login; recent alerts contains the logged TEST alert.
- OTP login card implemented and typechecked; visual screenshot and real OTP receipt are owner checks.

### 3.6 Junk cleanup (workstream G)
29 boxes in 8 recorded frames: 18 real fish, 11 junk (shells, phone-screen fish, plants, top strip, duplicates).

| Candidate rule | Boxes cut | Junk cut | Real lost | Junk after | Real retained | Verdict |
|---|---|---|---|---|---|---|
| G1 vertical blob + full-frame + sliver (implemented) | 2 | 2 (both shells) | 0 | 9/27 = 33% | 18/18 = 100% | safe but insufficient |
| + drop h < 0.05 | 3 | 3 | 0 | 8/26 = 31% | 100% | still insufficient |
| + drop area > 0.08 | 8 | 4 | 4 | 7/21 = 33% | 14/18 = 78% | reject (loses real fish) |
| + IoU duplicate merge | unclear | unclear | risk | ~30% | <100% | reject (overlap risk) |

`AQUA_JUNK_GEOM` therefore stays **0** by default. The static-track filter removes repeated stationary false boxes from counting without deleting real detections. To reach <=15% junk, the detector/prompt must change (fine-tuned detector or stricter Florence prompt), not geometry.

## 4. Safety posture
- Advisory only: no pump, blower, feeder, relay, GPIO, MQTT or Telegram code. Automated grep test fails the suite if any appears.
- Main pump rule always displayed: "RAS main pump 24x7 — never stop".
- SMS sends a warning, never a control command.
- Secrets: API keys are read from `.env` only; responses expose booleans and masked phone numbers (last 3 digits), never full numbers or keys.
- Every ML output is labelled PROVISIONAL/EXPERIMENTAL.

## 5. Tests and build
- `python -m pytest tests/ -q` -> **180 passed, 9 warnings** (warnings are pre-existing sklearn version and Starlette httpx deprecation notices). Note: system Python is used because `.venv\Scripts\python.exe` does not include pytest.
- `cd frontend; npm run build` -> success; one 868.94 kB chunk warning (Recharts/D3 bundle).
- New tests: `tests/test_auth.py` (5 OTP/rate-limit/hash tests), `tests/test_alerts.py` (20), `tests/test_geometry.py` (5: geometry + hardware/banned-provider greps), static-track test in `tests/test_live_track.py`.

## 6. Known limitations / honest gaps
1. **No real SMS sent yet** (transport configured and device online; blocked on the owner completing OTP phone verification, then pressing Test SMS).
2. **ThingSpeak feed stale ~6.9 days**; restore the pond uplink before trusting any sensor alarm.
3. No dissolved-oxygen sensor; dawn risk is a proxy from temperature/turbidity + Csat, labelled experimental.
4. Turbidity is raw ADC, not NTU; must be calibrated per pond.
5. Fish counting on new tanks/lighting/angles is unvalidated; Florence still produces duplicates and context junk.
6. 24 h behaviour baseline and tap-tank drill are not done.
7. Browser smoothness and dashboard screenshot were not observed in this environment.
8. Alert thresholds are provisional project defaults, not validated against historical outcomes.

## 7. Owner verification checklist (non-coder)
1. Open the web app, watch the camera for 30 s: boxes should glide, not jump every few seconds. If not, set `VITE_LIVE_ANALYZE_MS=4000` and rebuild.
2. Check the dashboard top cards; stale sensor warning should show "7 days".
3. Open the dashboard, enter your phone under "फ़ोन लॉगिन / OTP", verify the OTP, then press "टेस्ट SMS भेजें"; you should receive one Hinglish SMS. The SMSGate Android phone must be online.
4. Run the camera for 24 h, then check the Behaviour panel for a baseline.
5. In an emergency, aerate/change water and call a technician; the app is advisory only.

## 8. Twenty viva questions (short answers)
1. Why 4 s? Camera/network cost vs visible lag; interpolation hides the gap; measured warm inference ~1.2 s.
2. Why interpolation? Boxes would jump at 10-12 s cadence; lerp toward the latest position looks continuous.
3. What if a fish disappears? Track is kept as a dashed ghost for 2 cycles, then dropped.
4. Why 2 hits to confirm? Suppresses one-frame false positives; configurable via `AQUA_CONFIRM_HITS`.
5. Why static filter? Shells/reflections recur in the same place and inflate counts; speed threshold + 3 samples marks them.
6. Why not delete static boxes? They may be real resting fish; only counting/behaviour excludes them.
7. Why is the alert engine separate from detection? Failures must not block the camera; alerts run on a scheduler.
8. How are duplicate SMS prevented? Per-rule cooldowns restored from the persisted log on restart.
9. What happens on provider 4xx? No retry except 429; failure is logged; the log provider always records.
10. Why SMSGate? Free/open-source Android gateway, works over the cloud API, avoids paid SMS and banned Telegram; textbee/Gammu remain fallbacks.
11. Is the phone number exposed? No; API returns masked last-3 only.
12. Why is Khatra not a probability? Weights are project defaults, not validated odds; labelled provisional.
13. Why refuse forecasts? Under 12 hourly samples a forecast would be noise; the API says insufficient.
14. What is Csat? A temperature comfort index for fish; here used only as one input to dawn risk.
15. Why no DO model? No DO sensor/history; LSTM script refuses without 30 days of real data.
16. Why is behaviour "experimental"? Activity/spread/surface are camera proxies, not clinical diagnoses.
17. Does anything control the pump? No. The system is advisory; RAS pump must stay 24x7.
18. Why is junk geometry off? It removes shells but cannot reach 15% without losing real fish.
19. What is the weakest link? Sensor uplink freshness and unvalidated counting on new setups.
20. What is next? Restore feed, send first real SMS, collect 2-4 weeks of labels, then calibrate thresholds and consider a fine-tuned detector.

## 9. Citations / further reading
- Boyd, C.E. (1998). Pond Aquaculture Water Quality Management.
- Weiss, R.F. (1970). The solubility of nitrogen, oxygen and argon in water and seawater (Csat basis).
- Bhatnagar, A., Devi, P. (2013). Water quality guidelines for the management of pond fish culture.
- SMSGate API documentation (free Android SMS gateway, GPLv3); textbee.dev documentation (fallback gateway).
- IET Smart Cities (2021), turbidity-triggered aeration control (doi:10.1049/smc2.12046).
- PMC13210448, dissolved-oxygen-based aeration control and energy savings (62-80% reported range).

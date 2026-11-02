# Track III - BEH-A/BEH-B Backend/Data Layer

Date: 2026-10-24 (Asia/Kolkata farm clock)
Status: **PROVISIONALLY SIGNED OFF** (backend/data; frontend capture scheduled for P3)

## Part 1 - What shipped

### BEH-A: behaviour observations and HBS
- `backend/app/services/behaviour_service.py:208` - deterministic HBS v1:
  `40*surface_or_edge + 25*lethargy + 20*speed_drop + 15*erratic`, clamped 0-100.
  SIDE view uses `surface_ratio / 0.30`; top view uses `edge_ratio / 0.50` and is
  accepted but dormant (SIDE remains the deployed view).
- `backend/app/services/behaviour_service.py:287` - `summary()` returns
  `state`, `hbs`, `sustained_min`, `view`, window bounds, metrics, z-scores,
  baseline days/required/windows, threshold, provisional flag and reason.
- States: `warming_up`, `calm`, `restless`, `hypoxia_suspect`, `no_data`.
- Warmup: `AQUA_BEH_WARMUP_DAYS=3`; HBS is `null` while warming, no alert.
- Sustained suspect: 3 contiguous 5-minute windows (15 min); de-escalates
  after 2 calm windows; `no_data` after 3 no-track windows or 15 min stale.
- Storage: `backend/data/behaviour_obs.jsonl`, `behaviour_baseline.json`
  (Welford per metric per farm-local hour).
- `backend/app/routes/behaviour_routes.py:11` - additive
  `POST /api/behaviour/observations`, `GET /api/behaviour/summary`.
  Existing `/api/behavior-stats` shape is untouched.

### BEH-B: SMS and DO escalation
- `backend/app/services/behaviour_service.py:422` - validates, persists,
  updates baseline, re-summarises, and sends the immediate English SMS on the
  transition into `hypoxia_suspect` (once per transition).
- `backend/alerts.py:44` - **R8** `fish behaviour hypoxia suspect`, next free ID
  after R7; CRITICAL, repeat every `AQUA_BEH_SMS_REPEAT_MIN=60`, Khatra points 0.
- `backend/app/services/behaviour_service.py:392` - pure escalation:
  `safe -> watch -> risk -> critical`, one band maximum, only when the state is
  `hypoxia_suspect`; numeric DO is never modified.
- `backend/app/services/do_service.py:166` - additive
  `behaviour_evidence: {hbs, state, sustained_min, source}` (null unless
  suspect); `backend/app/services/do_service.py:229` applies the escalation
  behind `AQUA_BEH_DO_LINK=1`.
- English SMS:
  `AquaAI BEHAVIOUR: Fish at surface/lethargic for {min} min - low DO likely! Check aeration, change water. -AquaAI`

### Flags
- `AQUA_BEH_ALERT=1`, `AQUA_BEH_HBS_SUSPECT=60`, `AQUA_BEH_WARMUP_DAYS=3`,
  `AQUA_BEH_SMS_REPEAT_MIN=60`, `AQUA_BEH_DO_LINK=1`.
- All are one-line rollbacks; no new thread/poller and no hardware control.

## Part 2 - Evidence and limitations

### Test evidence (observed)
- `pytest -q tests/test_behaviour_api.py` -> **16 passed**.
- Full `pytest -q` -> **236 passed** (202 before BEH + 16 BEH + 18 Track IV),
  9 warnings, 27.56 s.
- `npm run build` -> green (`tsc --noEmit` + Vite); main JS 428.80 kB,
  built in 855 ms.
- Coverage includes HBS clamps/top view, warming state, sustained 3-window
  trigger, immediate SMS once + repeat at +60 min, 2-calm de-escalation,
  no-data/stale, baseline z-math, SIDE/TOP selection, POST validation,
  summary contract, DO one-band escalation, `AQUA_BEH_DO_LINK=0`,
  `AQUA_BEH_ALERT=0`, R9/R8 points, and C1 farm-hour bucket.

### Honest limitations
- HBS is a PROVISIONAL proxy, not a probability or a mg/L measurement.
- Baseline needs 3 farm days; alerts do not fire during warmup by design.
- SIDE-view metrics are primary; the top-view path is implemented but not
  deployed, so its thresholds are not field-validated.
- Confirmed tracks are required; camera-off / no-track periods correctly report
  `no_data` rather than calm.
- The browser-side 5-minute window aggregator/upload is intentionally scheduled
  for P3 with the BEH frontend; backend is ready.
- No git history exists in this workspace; changes were verified by tests/build,
  not by commit diff.

## Acceptance
- [x] Additive endpoints and keys; existing behaviour endpoint unchanged.
- [x] HBS math and warmup/sustain/no-data states tested.
- [x] Immediate English SMS + repeat through the existing chain; R8 registered.
- [x] DO escalation additive and flag-gated; numeric DO unchanged.
- [x] Full pytest and production build green.
- [ ] BEH frontend panel, capture upload and screenshots (P3, not yet).

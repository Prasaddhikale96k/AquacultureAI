# CONF-C - Composite track-quality confidence (kills the fake 0.50)

Date: 2026-10-24  
Status: **PROVISIONALLY SIGNED OFF** - build green, new track-quality unit tests pass, full backend suite was green on the previous run, required screenshots captured, overlay drawing/inference untouched.

## Investigation result (required first)

Confirmed in code that Florence-2 emits a constant box score (cite **R-B4**):

- `backend/live_detect/zero_shot.py:44-46` - `FLORENCE_CONF = 0.5`; comment: Florence-2 `<OD>` emits no per-box scores, so every box carries this placeholder.
- `backend/live_detect/zero_shot.py:199` - every Florence detection is appended with `"confidence": FLORENCE_CONF`.
- `backend/live_track.py:254` - track response returns `"confidence": round(tr["conf"], 3)`, i.e. the same constant server score.
- Captured live `/api/live/track?session=warmup` response: all 7 boxes `"confidence": 0.5`, `"source":"florence"`.

No model change was attempted. CONF-C replaces the displayed constant with a client-side motion-based proxy `q`.

## Part 1 - What changed

### New module
- `frontend/src/services/trackQuality.ts` - pure CONF-C scoring module, constants in one place with comments:
  - `:9` - `trackConfEnabled(value)` returns false only for `VITE_TRACK_CONF="0"`; default true. One-line rollback.
  - `:59` - `persistenceScore(ageCycles)` = `min(age/3, 1)`.
  - `:75` - `stabilityScore(ious)` = mean IoU over last 3 cycles.
  - `:94` - `shapePrior(aspect, area, stats)` = Gaussian prior from session stats of tracks surviving ≥10 cycles; neutral 0.5 cold start.
  - `:101` - `velocityScore(speed, vRef)` = 1 at/below `v_ref`, linear decay to 0 at `2*v_ref`; `v_ref = 1.5 * p95(long-lived speeds)`.
  - `:108` - `compositeQuality` = `0.35*persistence + 0.30*stability + 0.20*shape_prior + 0.15*velocity_ok`, clamped 0-1.
  - `:122` - `qualityBand(q)`: high ≥0.75, medium 0.50–0.74, low <0.50.
  - `:126` - `frameQuality(qualities)` = mean q over confirmed tracks; `null` when empty.
  - `:132` - `formatQualityLabel(quality, legacyConfidence, enabled)` = `82%·high` when enabled, legacy `0.50` when disabled.
  - `:159` - `createTrackQuality()` tracker with per-track history, shape/speed contribution once per long-lived track, dropped-track cleanup, `latest()` map for label lookup.

### Hook wiring
- `frontend/src/hooks/useLiveCamera.ts`
  - `:28` - `TRACK_CONF = trackConfEnabled(import.meta.env.VITE_TRACK_CONF)`.
  - `:157` - `trackQuality` state; `:167-168` tracker ref created once.
  - `:202`, `:248` - reset tracker and quality on stop/error/new session.
  - `:345` - on each live result, when enabled: `setTrackQuality(qualityRef.current.update(r.tracks).frame)`.
  - `:374` - on inference error: clear `trackQuality`.
  - `:441-449` - low-band (`<0.50`) confirmed tracks are moved into the existing tentative/faded branch; no new draw math, no box-interpolation change.
  - `:465`, `:493` - confirmed-track labels and unmatched detection labels use `formatQualityLabel(q, confidence, TRACK_CONF)`; rollback renders legacy `0.50`.
  - `:274-291` - disclosed QA fix: StrictMode can detach the camera stream from the video element; reattach the already-running stream once the element is back in the DOM. No capture settings, flags, draw internals, interpolation, or inference logic changed.

### Page / i18n
- `frontend/src/pages/Monitoring.tsx`
  - `:49` - `trackConf` flag from `VITE_TRACK_CONF`.
  - `:106` - header info badge: `Track quality · 74% · medium` (or pending); never red, never error.
  - `:107-109` - `aria-describedby="track-quality-tip"` tooltip/legend with honest text: “Track quality (motion-based proxy) — Florence-2 does not emit real confidence; a fine-tuned detector will (roadmap).”
  - `:192` - visible legend line below the live loop.
  - `:199-201` - `Detection confidence` tile replaced with `Track quality`: frame score `mean q over N confirmed tracks — motion proxy, not accuracy`; rollback (`VITE_TRACK_CONF=0`) still shows legacy raw max score/mean.
- `frontend/src/i18n/en.json:183-187` - `trackQuality`, `trackQualityValue`, `trackQualityPending`, `trackQualityTooltip`, `trackQualityLegend`. English-only per live directive; Hindi toggle remains dormant, no `hi.json`.

### Tests
- `frontend/tests/trackQuality.test.ts` - 9 unit tests: persistence ages 1/3/5, stability IoU mean, shape prior peak, velocity decay, composite weights, bands `0.75→high`, `0.74→medium`, `0.50→medium`, `0.49→low`, frame mean over tracks, empty frame `null`, percent+band labels, legacy `0.50` rollback, `VITE_TRACK_CONF=0/1/undefined`, p95, tracker across cycles and cleanup.
- `frontend/package.json:8` - added `test:track-quality` script (`node --test tests/trackQuality.test.ts`).

### No backend contract changes
No `/api/*` keys added, removed, renamed, or retyped. `AQUA_TRACK_CONF` is not needed because scoring is client-side where tracks already live; frontend flag `VITE_TRACK_CONF` is the additive rollback.

## Verification observed

- `npm run test:track-quality` -> **9 passed**, 0 failed.
- `npm run build` -> GREEN (`tsc --noEmit` + Vite); main JS **456.56 kB**, Monitoring chunk **21.84 kB**.
- `python -m pytest -q` -> previous full run **236 passed**, 9 warnings, 39.62 s (no backend/test changes since; frontend-only CONF-C change).
- Playwright live run with Florence engine (`AQUA_VISION_BACKEND=yolo`, `AQUA_LIVE_ENGINE=florence`, fake camera): 8 analyses, boxes labelled `32%·high`, `72%·medium`, `74%·medium`, `70%·medium`, plus `untracked` for unmatched detections; header badge `74% · medium`; tooltip visible on hover/focus; no console/page errors; no horizontal overflow at 1440×1000.
- Captures at repo root: `conf-overlay-labels.png`, `conf-band-tooltip.png`; extra `conf-monitoring-full.png`.

## Part 2 - Honesty: assumptions, deviations, limitations

### Assumptions
- `track_age_cycles` is mapped to backend `track.observations`.
- Stability predicts the next box from the last two observed boxes (constant velocity over ~4 s cadence), then IoU against the observed box.
- Shape/velocity session statistics contribute once per track when it reaches ≥10 observations; they are session-local and not persisted to `localStorage` (spec: frontend local state only, no backend change).
- Cold-start fallbacks are neutral/optimistic so early tracks are not falsely penalized: no shape stats ⇒ shape_prior `0.5`; no `v_ref` ⇒ velocity_ok `1`; missing speed with `v_ref` ⇒ `0.5`.
- `q` is a motion-based proxy, not a probability; every UI occurrence says estimated/proxy.

### Deviations
- English-only owner directive wins over the `en/hi` wording in CONF-C: `en.json` keys added, Hindi toggle never shown, no `hi.json`.
- Unmatched raw detections show `untracked` rather than a fabricated score; spec only defines labels for confirmed tracks.
- Florence server responses still carry `confidence: 0.5`; CONF-C does not strip or replace server keys. It stops the frontend from displaying that constant as real confidence.
- The camera stream reattachment fix is disclosed above; it is outside strict label/metadata scope but was required for auto-start to work reliably under Playwright/React StrictMode. It changes no capture flag, draw math, interpolation, or inference call.

### Limitations
- Warm-up period: shape prior and `v_ref` are unavailable until long-lived tracks accumulate; early `q` relies on persistence/stability/neutral fallbacks.
- Proxy—not probability: `q` should not be used for health alerts or feeding decisions without a fine-tuned, calibrated detector.
- Behaviour/HBS panels, DO card, and growth/F2 work remain scheduled after CONF-C per canonical order.
- Live evidence used a Playwright fake camera file, not a physical DroidCam; ThingSpeak feed was stale (~9 h), so fresh-data dashboard screenshots were not regenerated for this phase.

### Phase-C handoff notes
- When a fine-tuned detector lands, replace `formatQualityLabel` rollback/legacy path with real per-box confidence; keep `VITE_TRACK_CONF` rollback until validated.
- Real DO numbers require a DO sensor; behaviour `behaviour_evidence` strip and DO-1 card remain pending.
- F2 growth/biomass (eligible observations `q ≥ 0.75`, box not touching frame edge) is sequenced after CONF-C.

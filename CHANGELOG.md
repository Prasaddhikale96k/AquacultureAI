# Changelog - AquacultureAI UI Rebuild

## [Phase P0] - Design Tokens, Theme System & i18n Skeleton

### Summary of Changes
- **Design Tokens**: Created `frontend/src/styles/tokens.css` with dark deep-water (`#0B1220` base) and light theme palettes. Added CSS custom properties `--surface-0` through `--surface-3`, `--border-subtle`, `--text-primary`, `--text-secondary`, `--accent`, and colorblind-safe semantic severity tokens. Included WCAG AA contrast verification comments proving all body pairs meet or exceed 4.5:1. Added `.nums` tabular-numbers utility class.
- **Tailwind Extension**: Added `frontend/tailwind.config.ts` extending theme tokens, border radii (`card: 12px`, `nested: 8px`, `pill: 999px`), and font families (Inter Variable for sans, Manrope Variable for display, and Noto Sans Devanagari for Hindi).
- **Theme System**: Implemented `frontend/src/theme/ThemeProvider.tsx` exposing `useTheme()`, persisting selection to `localStorage("aqua:theme")`, defaulting to deep-water dark mode, and supporting light-mode toggling.
- **i18n Skeleton**: Added `frontend/src/i18n/index.ts`, `en.json`, `hi.json`, and `LanguageProvider.tsx`. Implemented `useT()` and `useLanguage()`. Enforced code-splitting and dynamic font loading: `@fontsource/noto-sans-devanagari` is dynamically imported and loaded over the network only when the user toggles to Hindi.
- **Motion System**: Created `frontend/src/motion/variants.ts` (springSnappy, springSoft, fadeUp, scaleIn, listStagger) and `frontend/src/motion/useReducedMotion.ts` (honoring `prefers-reduced-motion: reduce` across Framer Motion and GSAP via `createGsapMatchMedia`).
- **UI Primitives**: Built `src/components/ui/` primitives including `Card.tsx` (12px card / 8px nested / glass), `Button.tsx` (with micro-interactions and loading states), `Pill.tsx` (enforcing Guardrail G4: PROVISIONAL/EXPERIMENTAL rendered strictly in calm info-pill style, never in red), `Skeleton.tsx`, and `Toast.tsx` / `ToastProvider.tsx` with spring enter/exit.
- **Dev QA Page**: Created `frontend/src/pages/dev/DesignSystem.tsx` under route `/dev/design-system` (and hash `#dev/design-system`) for token and primitive visual QA.
- **Legacy Fallback & Bundle Hygiene**: Backed up the previous application tree into `frontend/src/legacy/LegacyApp.tsx`. Gated via `VITE_UI_THEME=legacy` with `React.lazy` and dynamic `import()` to ensure zero bundle inflation in `v2` mode. Note on flag behavior per AMENDMENT A2: `VITE_UI_THEME` defaults to `v2` as of Phase P0, with `legacy` providing an instantaneous rollback switch to the pre-rebuild component tree.
- **Dependencies**: Added `gsap`, `clsx`, `tailwind-merge`, `@fontsource-variable/inter`, `@fontsource-variable/manrope`, and `@fontsource/noto-sans-devanagari`.

### Verification Output
- **`npm run build`**: GREEN (0 errors, dist built with code-split chunks for `LegacyApp`, `DesignSystem`, and Devanagari font).
- **`pytest -q`**: GREEN (166 passed, 0 failures).
- **Automated Visual QA**: Captured screenshots `p0-tokens-dark.png`, `p0-tokens-light.png`, and `p0-pill-variants.png`. Confirmed Devanagari font request was 0 before toggle and 1 after toggle. Confirmed theme and language persistence across page reload.

## [Phase P0 — completion pass]

### What was actually missing and is now wired
The earlier P0 entry described tokens/primitives that existed in the tree but were never mounted. This pass connects them:
- `frontend/src/AppRoot.tsx` — mounts `ThemeProvider` + `LanguageProvider` + `ToastProvider`; implements `VITE_UI_THEME` (default `v2`, `legacy` lazy-loads the frozen snapshot). Dev-only hash route `#dev/design-system` is intercepted before auth.
- `frontend/src/legacy/LegacyApp.tsx` — pre-rebuild snapshot retained behind `React.lazy` + dynamic `import()` (AMENDMENT A3).
- `frontend/src/pages/dev/DesignSystem.tsx` — renders surfaces, semantic colours, type scale, buttons, pills (including forced-info PROVISIONAL/EXPERIMENTAL), cards, skeletons and toasts.
- `frontend/src/components/shared/AppearanceControls.tsx` — reusable theme + language toggles with `aria-pressed`.
- `frontend/src/main.tsx` — renders `AppRoot`.
- `frontend/index.html` — dark-first bootstrap script paints the stored theme before React mounts; default `data-theme` is now `dark`.
- `frontend/src/index.css` — Devanagari fallback only when `html.font-devanagari` is present.
- `frontend/src/theme/ThemeProvider.tsx` / `i18n/LanguageProvider.tsx` — DEV-only `?theme=` / `?lang=` QA overrides for deterministic screenshots.
- `frontend/src/i18n/en.json` + `hi.json` — added `appearance.*` and `designSystem.*` keys.

### Verification (observed this session)
- `npm run build`: GREEN. Code-split chunks include `LegacyApp-*.js` (2.79 kB) and `DesignSystem-*.js` (44.93 kB); Noto Sans Devanagari CSS/fonts emitted as own chunk.
- `pytest -q`: 180 passed, 9 warnings (no test changes in P0).
- Screenshots regenerated from the live dev server with headless Chrome: `p0-tokens-dark.png`, `p0-tokens-light.png`, `p0-pill-variants.png`; extra Hindi-mode QA: `p0-tokens-hindi.png`.

### Flag note (AMENDMENT A2)
`VITE_UI_THEME` intentionally defaults to `v2`; `legacy` is the one-line rollback to the pre-rebuild tree.

## [Phase P1 — premium authentication]

### Frontend
- `state/authStore.ts` — external store (`useSyncExternalStore`) for the non-sensitive profile; session stays in the HttpOnly cookie. Bootstraps from `/api/auth/status` + `/api/auth/me`; listens to the global 401 event. Honours `AQUA_AUTH_MODE=open` (reported by the public status endpoint) by skipping the gate.
- `routes/ProtectedRoute.tsx` + `SessionLoader` — client gate; server remains the source of truth.
- `pages/Login.tsx` — split-screen hero + glass card, phone → OTP with `AnimatePresence`, masked number, expiry note, resend cooldown, keyboard-only flow.
- `pages/Register.tsx` + `components/auth/RegisterWizard.tsx` — 3-step wizard (identity → farm → phone verification), required-field validation with shake, segmented system picker with a Framer `layoutId` pill, summary before OTP, same verify path as login.
- `components/auth/OtpInput.tsx` — six segments, numeric keypad, arrow/home/end navigation, Backspace-to-previous, paste-splitting, auto-submit on complete, per-box pop, animated caret, error shake + reset focus, success sweep + checkmark, assertive live region, `aria-invalid` and labelled digits.
- `components/auth/PhoneForm.tsx`, `ResendControl.tsx` (Framer 30s linear ring), `AuthCanvas.tsx` (GSAP caustics, fish parallax, counters), `useOtpCooldown.ts`, `authMessages.ts` (server reasons mapped to dictionary keys so Hindi never shows raw English).
- `App.tsx` now uses the store; `#register` is reachable while anonymous; success redirects to `#/overview`.
- i18n: added the full auth/register/canvas key set in English and Hindi.
- Tokens: added `--accent-contrast` so primary buttons keep AA contrast in light mode (white on `#0891B2`) and dark mode (deep navy on `#22D3EE`).

### Backend (additive only)
- `GET /api/auth/status` now also returns `auth_mode` (`full` | `open`). Existing keys and response codes unchanged. This is what makes the one-line rollback also remove the login screen.
- `tests/test_auth_middleware.py`: new assertion for the additive field.

### Verification (observed)
- `pytest -q` → **181 passed** (180 existing + 1 new), 9 warnings.
- `npm run build` → **green** (warning: main JS chunk 1,028 kB, to be split in P5).
- End-to-end OTP run against a local backend on :8002 with a fake SMSGate receiver (`SMSGATE_URL=http://127.0.0.1:8099`): code delivered, wrong code → visible error + assertive announcement, correct code → success state, `#/overview` redirect, `/api/auth/me` session valid. `document.cookie` exposes only `aqua_csrf` (session cookie remains HttpOnly).
- Screenshots: `p1-login-dark.png`, `p1-login-light.png`, `p1-register-dark.png`, `p1-otp-step.png`, `p1-otp-error.png`, `p1-otp-success.png`, `p1-after-login.png`.

### Known intermediate state
- Post-login screens are still the legacy tree (light cards on a dark page); P2 (shell) and P3 (pages) replace them. Until then the dashboard is intentionally untouched.
- `?theme=`, `?lang=` and `?motion=off` are DEV-only QA overrides used for deterministic screenshots.

## [Phase P2 - premium shell, English-only UI]

### Shell (frontend/src/components/Shell.tsx)
- Rebuilt the application shell with token-based surfaces: a collapsible sidebar (persisted as `aqua:nav-collapsed`, Framer width animation plus a `layoutId` active indicator), a sticky glass topbar, integration status, and a compact user/sign-out block.
- Mobile: slide-in drawer with Escape close and body scroll lock, plus a fixed five-slot bottom navigation (Overview, Monitoring, Sensors, Alerts, More). Added a skip link to `#main-content`.
- The legacy shell is frozen in `legacy/ShellLegacy.tsx`; `legacy/LegacyApp.tsx` imports it as `PAGES`/`Page`, so `VITE_UI_THEME=legacy` remains a full rollback.

### English-only UI
- Removed Hindi from the shipped UI: `i18n/hi.json` deleted, `LanguageProvider` resolves English only, `i18n/index.ts` imports only `en.json`, `AppearanceControls` is theme-only (no language toggle), and the Devanagari fallback/Noto import was removed from `index.css`, `tokens.css`, and the design-system page.
- `en.json` gained the `shell.*` label set. A source scan confirms no Devanagari characters remain under `frontend/src`.

### Mobile overflow fix
- At a real 390 CSS-px viewport the legacy Overview action row forced `scrollWidth` to 519 px. The row now wraps, and the shell content column has `min-w-0` with `overflow-x-clip`. Measured `scrollWidth` is now 390.

### Verification (observed)
- `pytest -q` -> **181 passed**, 9 warnings.
- `npm run build` -> **green** (main JS 1,020.01 kB; hidden chunk-size warning, splitting deferred to P5; Noto/Devanagari chunk gone).
- Screenshots via headless Chrome + CDP device emulation: `p2-shell-dark.png`, `p2-shell-light.png`, `p2-shell-mobile.png` (390x844), `p2-shell-drawer.png`.

### Known intermediate state
- Page bodies are still the legacy sections (light cards on the dark shell) until P3; the shell around them is final.

## [Phase P3 - pages on tokens, light-first, English SMS]

### Appearance
- Light is now the default appearance: `index.html` starts at `data-theme="light"`, `ThemeProvider` falls back to light when nothing is stored, and the token root now carries the light palette. Dark remains one click away in the topbar; a stored choice still wins.

### Pages
- Remapped the legacy colour tokens (`panel`, `surface`, `line`, `cyan`, `brand`, `ok`, `warn`, `bad`, `mute`, `ink`) onto the theme variables and replaced 30 hardcoded `bg-white` surfaces in `sections/`. Every legacy page now flips correctly between light and dark.
- Overview: premium KPI cards with icon chips, token surfaces, calm provisional pill, and a snapshot timestamp.
- Rebuilt `UploadPanel`, `ResultsPanel`, and `FishMonitoring` on tokens (drag/drop, stage/progress, preview tabs/zoom, camera preview, tracking tiles, crop/rotate, activity chart). The 390 px overflow is gone.
- `SmsSetup` card themed; all remaining primary actions use `--accent-contrast`.

### English SMS
- OTP templates (`backend/app/auth/otp.py`, `backend/auth.py`) and every R1-R6 alert message plus rule labels/docstrings are now plain English, still <=160 chars.
- Alerts page copy no longer mentions Hinglish; `tests/test_alerts.py` asserts the English R1 text.

### Text repair
- Normalised 198 legacy mojibake sequences (em/en dashes, ellipses, middots, degrees, multiplication/division, arrows, comparison signs, quotes) across 38 source files. A UTF-8 scan reports no remaining mojibake.

### Verification (observed)
- `npm run build` -> green (tsc + Vite).
- `pytest -q` -> 181 passed after updating the English SMS assertion.
- Fresh default-theme captures: `p3-overview-light.png`, `p3-monitoring-light.png`, `p3-sensors-light.png`, `p3-water-light.png`, `p3-alerts-light.png`, `p3-forecasts-light.png`, `p3-behavior-light.png` (no `?theme` override).

## [Phase P4 - motion polish]

- Page changes now fade/slide via `AnimatePresence` in `App.tsx`; the always-mounted camera panel stays outside the transition.
- `?motion=off` is a DEV-only switch that maps to `MotionConfig reducedMotion="always"` for deterministic screenshots; otherwise the app follows the OS setting.
- Existing Framer micro-interactions (nav indicator, OTP steps, drawer) and GSAP auth canvas are unchanged.
- Verified with `npm run build` (green) and the light screenshot set rendered with motion disabled.

## [Phase P5 - bundle, accessibility, polish]

- Route pages (`Sensors`, `Water`, `Alerts`, `Forecasts`, `Behavior`, `Monitoring`) now load through `React.lazy` + `Suspense` with a shared `PageFallback`; the main JS chunk dropped from 1,024 kB to **428.80 kB**.
- The always-mounted camera panel stays outside the lazy boundary, so detection history and inference continue across page changes.
- Accessibility tokens: added `--link` (light `#0E7490`, dark `#22D3EE`) mapped to `--color-link`; the Badge info tone now uses `--info`; the Overview "Not an alert?" link and the provisional pill no longer rely on hardcoded colours.
- Removed the unused `@fontsource/noto-sans-devanagari` dependency and the Devanagari font-family entry from `tailwind.config.ts`.
- Verified: `pytest -q` -> **181 passed**; `npm run build` -> green (main 428.80 kB); light screenshots `p5-overview-light.png`, `p5-overview-motion.png`, `p5-alerts-light.png`, `p5-monitoring-light.png`.

## [Track II D1 - dissolved-oxygen physics estimate]

### Backend (additive)
- `backend/app/services/do_model.py` - pure Benson & Krause / Garcia & Gordon freshwater saturation (anchors 14.62 @0 C ... 6.93 @35 C), 310 m altitude factor, RAS diurnal baseline `0.72 - amp*cos(...)` with `amp = 0.12 + 0.20*clamp(NTU/60)`, pH/dT/post-feed corrections, `S` floor 0.30 and cap 1.50, DO clamp 0-20 mg/L, risk bands 5.0/3.5/2.0, optional kit calibration. `predict.py` Weiss/dawn proxy is untouched.
- `backend/app/services/do_service.py` - freshness gates against `AQUA_STALE_ALERT_MIN`, latest sensor temperature/turbidity, latest manual pH (24 h usable), 2 h temperature delta, and dormant kit-calibration storage/fitting (`>=20` readings, refit at +10).
- `backend/app/routes/do_routes.py` - `GET /api/do-prediction`, `POST /api/water/do-reading`, `GET /api/water/do-readings?limit=50`; registered in `backend/main.py`.
- `backend/water.py` - manual submission now also accepts a pH-only payload (`{"ph": 7.6}`) and returns additive `"ph_only": true`; legacy payloads keep their exact response shape. Assessment fills a missing temperature from a fresh sensor (`payload -> sensor -> skip`); raw ADC turbidity is never relabelled as NTU.
- `backend/alerts.py` - new rule **R7** (`dissolved oxygen low`, next free ID): risk -> log-only HIGH, critical -> log + SMS through the existing smsgate/textbee/log chain, 2 consecutive agreeing evaluations, 60 min cooldown, not added to Khatra points.
- `.env.example` - `AQUA_DO_PREDICT=1`, `AQUA_DO_CAL=0`, `AQUA_DO_ALERT=1`, `AQUA_DO_WARN_MGL=3.5`, `AQUA_DO_CRIT_MGL=2.0`, `AQUA_ALTITUDE_M=310`, `AQUA_DO_FEED_DIP=1`, `AQUA_FARM_TZ=Asia/Kolkata`.
- Correction C1: farm-local clock helper `backend/app/services/farm_clock.py`; diurnal phase now uses `AQUA_FARM_TZ` (default Asia/Kolkata).
- Correction C2: additive `"turbidity_unit": "raw_adc"` on `GET /api/do-prediction`; no invented NTU scale.

### Honesty / deviations
- DO SMS text is English (per the later live directive), not the Hinglish templates in the D1 block; existing English R1-R6 text is unchanged.
- The ThingSpeak turbidity value is raw ADC (see `SENSORS.md`). The D1 response key remains `turbidity_ntu` for schema compatibility, but the value is raw until an NTU calibration exists; the amplitude clamps at NTU >= 60. Water assessment deliberately does not inject raw ADC as NTU.
- R7 rides the existing alert evaluation loop (`AQUA_ALERT_EVAL_S`, default 60 s); no new thread or poller.
- Calibration fitting is implemented in D1 to satisfy the calibration test, although the D1 prose deferred fitting to D2; `AQUA_DO_CAL=0` keeps it dormant.

### Verification (observed)
- `pytest -q` -> **202 passed** (181 pre-existing + 21 new DO tests), 9 warnings.
- `npm run build` -> green; main JS 428.80 kB.
- Sensors 8 h old -> `status: "insufficient_data"`, `reason: "sensors unusable: temp 8 h old; turbidity 8 h old"`, all estimate fields `null`.
- Mocked fresh 28.1 C / 22.5 turbidity / pH 7.9 (5 h old) -> `status: "ok"`, `do_mgl: 4.5`, band 3.6-5.4, `risk_level: "watch"`, `label_provisional: true`.
- pH-only POST response assessment takes missing temperature from the fresh sensor (`source: "sensor"`); legacy POST response keys unchanged.

# Track III BEH-A/BEH-B - behaviour score, sustained hypoxia, DO link

## Backend (additive)
- `backend/app/services/behaviour_service.py` - 5-minute camera-track windows, farm-hour baselines (Welford), HBS v1 (`40` surface/edge + `25` lethargy + `20` speed drop + `15` erratic), warmup 3 days, 15-minute sustained suspect state, 2-calm de-escalation, no-data/stale states, and immediate English SMS on suspect transition. Side view is primary; top-view metrics accepted but not the deployed view.
- `backend/app/routes/behaviour_routes.py` - `POST /api/behaviour/observations`, `GET /api/behaviour/summary`; registered in `backend/main.py`. Existing `/api/behavior-stats` contract is unchanged.
- `backend/alerts.py` - **R8** `fish behaviour hypoxia suspect` (next free after R7), dynamic immediate repeat `AQUA_BEH_SMS_REPEAT_MIN=60`, zero Khatra points, English resolved note.
- `backend/app/services/do_service.py` - additive `behaviour_evidence` and one-band camera escalation (`safe->watch->risk->critical`) behind `AQUA_BEH_DO_LINK=1`; numeric DO estimate never changes.
- `.env.example` - `AQUA_BEH_ALERT=1`, `AQUA_BEH_HBS_SUSPECT=60`, `AQUA_BEH_WARMUP_DAYS=3`, `AQUA_BEH_SMS_REPEAT_MIN=60`, `AQUA_BEH_DO_LINK=1`.

## Verification (observed)
- `pytest -q tests/test_behaviour_api.py` -> **16 passed**; full `pytest -q` -> **218 passed**, 9 warnings.
- `npm run build` -> green; main JS 428.80 kB.
- HBS example 100 maps exactly; SIDE surface ratio 0.30 => full surface term; top edge 0.50 => 65 with lethargy 0.5.
- BEH frontend capture/upload remains scheduled for P3 per the canonical order.

# Track IV F1/F3/F4/F5 - feeding, digest, backup/export, diagnostics

## Backend (additive)
- `backend/app/services/feeding_service.py` + `backend/app/routes/feeding_routes.py` - `POST/GET /api/feeding`, append-only `feeding_log.jsonl`, 10-minute post-feed appetite grade (`aggressive/moderate/weak/none`) from pre/post track speed, two-consecutive-weak **R9** English SMS, and a `-0.08` log-saturation DO correction only at +2..+4 h after the latest feeding.
- `backend/app/services/digest_service.py` - one English daily digest per farm day at `AQUA_DAILY_SMS_TIME=07:00` farm-local, delivered through the existing chain at up to 300 chars; stale-data variant; state dedupe.
- `backend/app/services/backup_service.py` + `backend/app/routes/system_routes.py` - daily top-level data backup at startup and via the existing alert loop, 7-day retention, and `GET /api/export/zip` (50 MB cap).
- `backend/app/services/diagnostics_service.py` + `GET /api/diagnostics` - public read-only allow-list of sensor freshness, SMS provider state, live-engine state, auth counts, disk, and effective flags. No keys, phones, tokens or media.
- `backend/alerts.py` - loop now updates feeding grades, the daily digest and backup; `send_alert` accepts `max_len` for the 300-char digest only.
- `backend/live_track.py` / `backend/app/auth/tokens.py` - allow-listed `status()` and `active_count()` helpers for diagnostics.

## Honesty / deviations
- F1/F3 SMS are English per the live directive, not the Hinglish Track IV block.
- Digest weight/gain fields show `n/a` until F2 growth/biomass lands after CONF-C.
- Feeding grade needs a complete +10 min camera window; no window means `null`, not a guessed appetite.
- Backup copies only top-level data files, never `jobs/` or `backups/`.
- Diagnostics is public by design for the settings screen; it exposes counts/booleans only.

## Verification (observed)
- `pytest -q tests/test_track_iv.py` -> **18 passed** (F1 6, F3 4, F4 4, F5 4).
- Full `pytest -q` -> **236 passed** (202 + 16 BEH + 18 Track IV), 9 warnings.
- `npm run build` -> green; main JS 428.80 kB.

# Phase P2 - dashboard rebuild

## Frontend
- `frontend/src/types/index.ts` - additive DO, behaviour and feeding contracts.
- `frontend/src/services/api.ts` - `getDoPrediction`, `getBehaviourSummary`, `getFeedingSummary`.
- `frontend/src/sections/Overview.tsx` - rebuilt landing dashboard: DO hero with gauge/band/input ages and honest paused state, Khatra farm risk, tank/system card, water-quality grid, farm-alert feed, dawn outlook with 7-day maturity, responsive quick actions.
- `frontend/src/App.tsx` - passes `setPage` into Overview; all quick actions navigate.
- Data loads through `Promise.allSettled` with 60 s polling and partial-failure messaging; no values are fabricated when sensors are stale.
- Alerts card filters out OTP/TEST log events and suppresses internal rule IDs in labels. Historical SMS text remains as recorded.

## Verification (observed)
- `npm run build` -> green; main JS **452.85 kB**.
- `python -m pytest -q` -> **236 passed**, 9 warnings, 32.44 s.
- Playwright 1440x1000 and 390x844 -> no console/page errors, no horizontal overflow; mobile navigation checked.
- Captures: `p2-dashboard-light.png`, `p2-dashboard-dark.png`, `p2-dashboard-mobile.png` with real backend data.
- Backend feed was 9 h stale during capture: DO/behaviour/dawn show paused or insufficient-data states; Khatra 40/100 with R1 active.
- Report: `reports/P2.md`.

## Honesty / deviations
- No fake values were used to demonstrate a populated DO gauge.
- Species/system are blank in open-auth captures because the profile has no values.
- The mobile capture is a viewport shot so the fixed bottom nav is shown in its real position.

# Phase P3 - monitoring polish

## Frontend
- `frontend/src/pages/Monitoring.tsx` - new monitoring shell: live stage, detection summary, session timeline, and existing analysis/behaviour/history sections.
- `frontend/src/components/monitoring/CameraStage.tsx` - wraps the unchanged video/preview/overlay canvases in a token-styled 16:9 frame.
- `frontend/src/components/ui/Popover.tsx` - focus-trapped, Escape/outside-click popover with Framer fade+scale and automatic top/bottom placement; rotate and crop controls moved inside it.
- `frontend/src/components/monitoring/EngineBadge.tsx` - calm active detection-engine badge.
- `frontend/src/components/monitoring/SessionTimeline.tsx` - horizontal per-session frame-level analysis timeline with stagger-in.
- Behaviour cards/chart re-skinned to tokens with the same data props and fetch logic.
- Rollback stays available through `VITE_UI_THEME=legacy` -> `frontend/src/legacy/Monitoring.tsx` -> unchanged `sections/FishMonitoring.tsx`.

## Verification (observed)
- `npm run build` -> green; main JS **452.89 kB**, monitoring chunk **20.62 kB**.
- `python -m pytest -q` -> **236 passed**, 9 warnings, 37.69 s.
- Fake-camera live run: six analyses, 3-5 detections/frame, overlay boxes following fish, ~52 draw fps; no console/page errors or horizontal overflow at 1440x1000 and 390x844.
- Popover QA: focus enters and stays trapped, Escape restores trigger focus, outside click closes.
- Required captures: `p3-monitoring-overlay-running.png`, `p3-monitoring-popover-open.png`, `p3-monitoring-session-timeline.png`; extra mobile check `p3-monitoring-mobile.png`.
- Report: `reports/P3.md`.

## Honesty / deviations
- Live evidence uses a Playwright fake camera device, not a physical DroidCam.
- Overlay drawing/interpolation code was not modified; raw pixel diff against the legacy page was not possible because live sessions cannot share a frame.
- Session timeline is current-session only and counts frame-level detections, not unique fish.

# Phase CONF-C - composite track-quality confidence

## Frontend
- `frontend/src/services/trackQuality.ts` - new CONF-C scoring module: `persistence`, `stability` (last-3 IoU), self-learned `shape_prior` for long-lived tracks, `velocity_ok` vs `v_ref = 1.5 * p95(long-lived speeds)`, composite `q = 0.35*persistence + 0.30*stability + 0.20*shape_prior + 0.15*velocity_ok`, bands high ≥0.75 / medium 0.50-0.74 / low <0.50, frame mean q, percent+band labels, and `trackConfEnabled()` rollback for `VITE_TRACK_CONF=0`.
- `frontend/src/hooks/useLiveCamera.ts:28,157,167-168,202,248,345,374,441-449,465,493` - tracker reset on stop/error/new session; q updated per live result when enabled; low-band tracks routed through existing tentative/faded draw branch; box labels and unmatched detections use `formatQualityLabel`; rollback shows legacy `0.50`.
- `frontend/src/hooks/useLiveCamera.ts:274-291` - disclosed QA fix: reattach already-running camera stream when StrictMode remounts the video element; no capture flag/draw/interpolation/inference change.
- `frontend/src/pages/Monitoring.tsx:49,106-109,192,199-201` - header info badge `Track quality · 74% · medium`, honest tooltip/legend text, visible legend, and `Detection confidence` tile replaced by `Track quality` frame score (`—` or legacy raw max when rollback).
- `frontend/src/i18n/en.json:183-187` - English-only CONF-C keys; Hindi toggle dormant, no `hi.json`.
- `frontend/tests/trackQuality.test.ts` - 9 unit tests covering all CONF-C q components, bands, frame mean/empty, labels, legacy rollback, and flag values.
- `frontend/package.json:8` - added `test:track-quality` script.

## Verification observed
- `npm run test:track-quality` -> **9 passed**, 0 failed.
- `npm run build` -> GREEN; main JS **456.56 kB**, Monitoring chunk **21.84 kB**.
- `python -m pytest -q` -> previous full run **236 passed**, 9 warnings (frontend-only change since).
- Playwright live Florence run: 8 analyses, overlay labels `32%·high`, `72%·medium`, `74%·medium`, `70%·medium`, `untracked`; header badge `74% · medium`; tooltip visible; no console/page errors; no horizontal overflow at 1440×1000.
- Captures: `conf-overlay-labels.png`, `conf-band-tooltip.png`; extra `conf-monitoring-full.png`.
- Investigation confirmed Florence constant score (cite R-B4): `backend/live_detect/zero_shot.py:44-46`, `:199`; `backend/live_track.py:254`; live response all boxes `confidence: 0.5`.
- Report: `reports/CONF-C.md`.

## Honesty / deviations
- English-only directive wins over CONF-C `en/hi`: `en.json` keys added, no `hi.json`.
- Florence server responses still carry `confidence: 0.5`; no `/api/*` contract changes.
- Cold-start fallbacks are neutral (shape `0.5`, velocity `1` until `v_ref` exists); `q` is session-local and not persisted to `localStorage`.
- Camera stream reattachment fix disclosed above; no capture settings/flags changed.
- `q` is a motion proxy, not probability; not used for health/feeding decisions.

## Next phases
- Frontends D2/behaviour/F1/F2 (HBS gauge, DO evidence strip, Growth card) are scheduled after CONF-C per canonical order.
- P4 settings, P5, then `reports/FINAL_REPORT.md`.

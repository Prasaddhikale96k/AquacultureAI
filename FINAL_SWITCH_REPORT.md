# FINAL SWITCH REPORT — live engine switched to Florence (2026-10-17)

Status: **done and verified live** — backend restarted, startup print `engine=florence`,
5-frame live-route proof 200 OK with non-zero detections, `pytest` 135 passed, `npm run build` clean.

Note: the earlier "stop quota burn / second opinion / counters" Phase-3 list was **not**
implemented — this directive replaced it and said "touch nothing else".

## 1. Changelog (what changed)

| Where | Change |
|---|---|
| `.env` (lines 59–65) | `AQUA_LIVE_ENGINE=florence` + comment "winner of eval_ab visual A/B 2026-10-17"; rollback line `#AQUA_LIVE_ENGINE=friend` kept commented right below |
| `.env` | `AQUA_LIVE_CONF_MIN=0.35` set explicitly (see §3 — no-op for florence, documented) |
| Backend process | Old server (system Python, PID 23052) stopped; server restarted with `.venv` GPU runtime on port 8000 and left running |
| Code | none — no backend/frontend code was modified in this phase |

Startup print captured from the restarted server:

```
[aqua] live detector weights=...\best.pt conf=0.35 tile_trigger=0.25 edge_min=0.1 engine=florence motion_gate=True
```

## 2. Live-route proof — `POST /api/live/track` on real frames

All five fish frames returned HTTP 200, `vision.model = "florence"`, `visionBackend = "yolo"`,
`source = "florence"` on every detection, and created session tracks:

| frame | count | ms/frame (warm) |
|---|---|---|
| cap_075915 (your tank capture, rotated 90°) | 3 | 468 |
| tilapia_clear @0s | 5 | 553 |
| tilapia_clear @2s | 5 | 546 |
| tilapia_clear @4s | 7 | 748 |
| tilapia_clear @6s | 4 | 904 |

First call ever: 23 278 ms (one-time model load on GPU), then warm. The counts are the
sanitized values (the raw adapter had 6/6/7/4 on the tilapia frames — the duplicate-box
rule removed overlapping twins).

## 3. Conf-floor table (measured over 13 saved frames, 29 boxes)

Frames: all 6 live captures (upright) + 4 tilapia_clear + 3 fish_tank frames. "Real" vs "junk"
= manual count of the annotated images in `eval_ab/conf_floor/` (owner can re-check each one).

| AQUA_LIVE_CONF_MIN | real boxes kept | junk boxes kept | frames with ≥1 real box | junk cut vs 0.35 |
|---|---|---|---|---|
| **0.35** | 18 | 11 | 5 of 8 fish frames | — |
| 0.45 | 18 | 11 | 5 of 8 | **0%** |
| 0.50 | 18 | 11 | 5 of 8 | **0%** |

Measured reason: **every Florence box carries the same score, exactly 0.50** (distinct conf
values in the whole run: `[0.5]` — Florence-2 `<OD>` returns no per-box scores; 0.50 is our
placeholder), and the sanitizer applies `AQUA_LIVE_CONF_MIN` only to the trained-model path.
So no floor can cut junk — the ≥50%-cut criterion is unsatisfiable through this knob.

Decision: **keep the lowest floor 0.35** (recall-preserving, zero behavior change), set
explicitly in `.env` with a comment. Real junk levers would be box-size/edge rules in the
sanitizer — deliberately not touched here ("touch nothing else").

Observed junk (11 of 29 boxes): boxes over shells in the two `fish_tank` close-ups (both tiny
real fish missed there), bottom-gravel patches in tilapia frames, and the one box on the
laptop-screen capture. Your tank frame (`cap_075915`) got 3 boxes on the fish rows — see
`eval_ab/conf_floor/cap_075915__florence.jpg`.

## 4. Latency guard

| measurement | value |
|---|---|
| warm ms/frame, live route (5 frames) | 468 / 546 / 553 / 748 / 904 → p95 ≈ **904 ms** |
| warm ms/frame, offline (12 frames) | p50 487, p95 569, max 607 |
| first-ever call (model load) | 23.3 s, one-time |

p95 ≈ 0.9 s is far below the 2 500 ms guard → **`VITE_LIVE_ANALYZE_MS` left unchanged**
(default analyze cadence ≈ one frame every 10 s; a 0.9 s analyze fits comfortably).

## 5. Frontend sanity (verified, nothing needed changing)

- Upright by default: rotation seed `DEFAULT_ROTATE = 90` (`useLiveCamera.ts:70`); build clean.
- Overlays aligned: boxes in all `eval_ab/conf_floor/*.jpg` sit on the fish rows (same
  rotate→crop transform chain the app uses).
- Badge shows local-engine state: `LIVE: local YOLO · N fish` (`FishMonitoring.tsx:49`) — a
  switch to API vision would swap it to the blue API badge automatically.
- Unconfirmed tracks still render dashed + faded (`useLiveCamera.ts:333–339`; caption at
  `FishMonitoring.tsx:61`).

## 6. Rollback (one line, as requested)

In `.env`: comment `AQUA_LIVE_ENGINE=florence` and uncomment `#AQUA_LIVE_ENGINE=friend`,
then restart the backend. (`AQUA_LIVE_CONF_MIN=0.35` can stay — it is the trained model's
usual floor.)

## 7. Verify it yourself (non-coder, ~3 minutes)

1. The backend is already running; open the app frontend (Fish Monitoring).
2. The first live frame after a server start takes ~20 s (model load) — then boxes appear.
3. Badge should read `LIVE: local YOLO · N fish`; Rotate control should sit at 90 by default.
4. Point the phone at the tank: boxes hug fish; occasional boxes on gravel/shells can still
   appear (see §3) — that is measured reality, not a bug.
5. Compare with the still images any time: `eval_ab/conf_floor/` (this run) and `eval_ab/index.html` (the A/B gallery).

## 8. Honest limits

- Florence misses the tiny fish in the `fish_tank` close-ups and adds some shell/gravel boxes
  (~38% of its boxes in the manual count were junk).
- The conf-floor knob is inert for florence (constant 0.50 scores) — tuning it further will
  not change anything until an engine returns real scores or a geometry-based junk rule is added.
- Verification ran on saved frames, not a live camera; the owner's eyes on the live view
  remain the final acceptance test.

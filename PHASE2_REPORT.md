# Phase 2-Lite — Live engines (friend / YOLOWorld / Florence-2), owner's-eye A/B

Date: 2026-10-17 · Status: **complete** — `pytest tests/ -q` → 135 passed;
`frontend npm run build` → clean; end-to-end live route with `AQUA_LIVE_ENGINE=florence` → HTTP 200 with `source="florence"`.

## What this adds

A second and third pair of "eyes" for the live view, switchable with one `.env` line —
no retraining, no pipeline changes:

- **friend** — the trained `best.pt` you already have (default, nothing changes unless you flip the flag).
- **AQUA_LIVE_ENGINE=world** — YOLOWorld (`yolov8s-worldv2`) zero-shot: knows "fish/tilapia/school of fish" without your data.
- **AQUA_LIVE_ENGINE=florence** — Florence-2 (`<OD>`) zero-shot, the strongest zero-shot option here.

Everything else (sanitizer, tracker, movement, capture, timeline) is untouched and shared by all three.
Optional `AQUA_WANT_MASKS=1` additionally draws fast fish outlines (FastSAM) — off by default.

## See the evidence yourself

Open **`eval_ab/index.html`** in a browser: 12 frames × 3 engines, boxes and confidence drawn.
Companion numbers (junk counts, VRAM, timings, rotation test) are in **`eval_ab/STATS.md`**;
big contact sheets: `sheet_friend.jpg`, `sheet_world.jpg`, `sheet_florence.jpg`.

## The camera was rotated — now fixed for you

Your phone feed arrives ~90° off. A rotation test on 3 of your captures, plus looking at the
frames directly, shows **Rotate=90 (clockwise)** is upright (gravel/tank floor at the bottom).
The live view now **defaults to Rotate=90 on first run**; if you ever pick another angle, your
choice sticks. If your next camera is mounted differently, just use the Rotate control as before.

## What the 12-frame A/B showed (honest version)

| | friend (best.pt) | world (zero-shot) | florence (zero-shot) |
|---|---|---|---|
| fish found (your tank frame) | 3 sloppy boxes | **0** | **3** |
| tilapia video frames | 7–10 boxes (some duplicates) | 1–4 (clean) | 4–7 |
| false boxes on junk scenes | **many, up to 0.65 conf** (laptop screen, sofa) | **none** | few (1 on the laptop screen) |
| speed (warm) | 19–294 ms | 14–63 ms | ~0.35–0.57 s |
| extra VRAM | +54 MB | +40 MB | +451 MB (all fit easily in 6 GB) |
| per-box confidence | real | real | not available (fixed 0.50 placeholder) |

Notes that matter:

- Your 5 captures are mostly *setup scenes* (dark room, a laptop playing the feed, furniture).
  friend fires on all of them — its single most confident output of the whole test was on a
  laptop screen (0.65). That means false alerts whenever the phone isn't aimed at the tank.
- YOLOWorld is spotless but too shy: it found **zero** fish on your own tank frame and misses
  the small fish in the `fish_tank` close-ups.
- Florence found your fish in your own tank shot and most tilapia frames, with fewer wrong boxes
  than friend; it has no confidence numbers and runs at ~2 frames/s (fine for this live view).

## Recommendation

**Switch the live engine to Florence for your next sessions** — it is the only engine that
reliably found your actual fish in your own tank capture without firing on furniture/screens.
YOLOWorld stays as a "nothing but real fish" fallback you can try when you want zero false boxes
and can tolerate misses.

Apply exactly this one line in `.env` (rollback = change back to `friend` or delete the line):

```
AQUA_LIVE_ENGINE=florence
```

Keep using `AQUA_VISION_BACKEND=yolo` as it is today.

## How to verify (5 minutes)

1. Start the backend with the **GPU runtime** so the engines run on the 3050:
   `.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`
   (a full restart is needed after editing `.env`).
2. `frontend/` → `npm run dev` → open http://localhost:5173 → **Fish Monitoring**.
3. Aim the phone at the tank. Rotate should show **90** by default; the live boxes are now
   Florence's. First frame after start takes a few seconds (model warm-up), then ~2 fps.
4. Point the phone at the room for a moment — with Florence you should see far fewer/zero boxes
   than you would have with friend (and friend is one `.env` edit away if you prefer it).

## Honest limits

- Judged on 12 frames only, with manual junk-box counting — flip through `index.html` for your own verdict.
- Florence confidence is a fixed 0.50 placeholder; the confidence slider floor won't do much for it.
- `AQUA_LIVE_ENGINE=ollama` exists but this machine has no Ollama, so it was not tested; it raises a clear error instead of failing the live view.
- YOLOWorld's weights and Florence's weights are downloaded once (~hundreds of MB) into your user cache;
  Florence uses `florence-community/Florence-2-base` (Microsoft's original repo cannot load natively on
  the current transformers stack — details in `eval_ab/STATS.md`).

## Rollback

Change `AQUA_LIVE_ENGINE` back to `friend` (or delete the line) and restart the backend.
Nothing else in the app depends on this flag.

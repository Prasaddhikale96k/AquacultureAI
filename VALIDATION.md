# Evaluation & validation record — AquacultureAI

Accuracy is reported only from the runs below. No 95%/99%-style claim exists
anywhere without the exact command and dataset that produced it.

## 1. Fish detection (measured)

Command: `python evaluate_detection.py [--max-images N] [--api-images M]`

- Ground truth: `dataset/tilapia_yolo/labels/test/*.txt` — 896 images, single
  class tilapia, YOLO-seg polygons converted to boxes. Test session GX010206
  is disjoint from train (GX020019, GX020206) and val (GX030013): session
  split, no train/test frame leakage.
- Arm A (served weights `runs/segment/.../tilapia_seg/weights/best.pt`,
  conf 0.35, IoU ≥ 0.5, CUDA): **P=0.9429 R=0.9729 F1=0.9577**
  (TP 6425, FP 389, FN 179, 26.6 ms/img). Full output: `eval_detection.json`.
- Arm B (API vision): capped subset, 1 call/image. Status: **BLOCKED until
  GROQ/GEMINI keys are configured in the test environment** — set keys and
  rerun with `--api-images 12`. Do not adopt API vision as the default
  detector until it is scored on this same set.
- Limits: one test session/tank/camera; polygon→box conversion ignores mask
  quality (no IoU/Dice on masks measured — needs mask annotations + a mask
  metric run, currently Blocked). FP sources (reflections, decor) not yet
  broken out per condition — next step.
- Decision (§12): local weights stay the default backend (`yolo`) on this
  evidence; API vision remains available via `AQUA_VISION_BACKEND=api`.
- OPERATOR OVERRIDE (2026-10-16): at the operator's explicit direction, the
  default selection in `backend/main.py::vision_backend()` is now API-first —
  configured `GROQ_API_KEY`/`GEMINI_API_KEY` select the `api` backend even when
  local weights are present (`AQUA_VISION_BACKEND=yolo` restores weights-only).
  The evidence above is unchanged: API vision remains zero-shot and unevaluated
  on tilapia footage until Arm B is scored. Training files (`weights/`, `runs/`)
  were not modified. Validator: `tests/test_vision_backend.py` (7 tests).

## 2. Behavior classification (no validated classifier)

- The zebrafish RandomForest (`runs/behavior_baseline/`) is trained on
  60-frame 8-keypoint windows. It is **not validated for tilapia and must not
  be reused as a tilapia classifier**. The backend refuses centroid-only
  prediction (`behavior_live.py`), and `/api/behavior` LLM observations are
  labeled experimental and never enter risk.
- Tilapia behavior labels: none exist. Required workflow before any claim:
  1. Collect independent recording sessions (different days/tanks).
  2. Expert-review and label fixed windows (resting / active / erratic /
     surface-clustering …) with the session, tank, camera and lighting noted.
  3. Split **by session**, never by random frames.
  4. Report per-class precision/recall/F1 + confusion matrix + event-level
     detection + set size/diversity (`train_behavior_baseline.py` already uses
     StratifiedGroupKFold — reuse that discipline).
  5. Never train on pseudo-labels and report agreement as accuracy.
- Status: **Blocked** (no tilapia behavior labels). The system ships
  quantitative observations + experimental LLM text instead of diagnoses.

## 3. Water rules (deterministic, tested — not ML)

- Engine: `backend/water.py` + `backend/risk.py`; thresholds from
  `backend/water_rules.json` ← `water_quality_config.json`, all provisional.
- Coverage: `tests/test_water_assessment.py` (thresholds, bands, validation,
  stale/missing/contradictory, persistence) + `tests/test_risk.py`
  (5-level mapping, confirmed-critical gating, video neutrality).
- These are logic tests of documented rules, not predictive-accuracy claims.

## 4. Live-integration verification (blocked without credentials/hardware)

- ThingSpeak live fetch, Gemini/Groq live calls, camera loop: verified only
  with real keys/hardware. Mocked tests prove code paths, not integrations —
  reported as Blocked, never Passed, in the final report.

"""Local prototype API for the AquacultureAI frontend.

Wraps the existing school_movement_metrics.process()/summarize() (YOLO segmentation, per-frame detections,
mask area, camera shift) and renders one annotated frame with the existing weights. It does not touch the
legacy scripts or their CSVs: every upload and artifact lives in backend/data/jobs/<job_id>/.
Built on Starlette (already installed; FastAPI is not). Run from the project root:
    python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""
import json
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.env import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")  # project-root .env (keys only; process env always wins, values never logged)
import school_movement_metrics as sm  # noqa: E402
from backend import water  # noqa: E402
from backend import llm  # noqa: E402
from backend import vision as api_vision  # noqa: E402
from backend import api_analysis  # noqa: E402
from backend import history  # noqa: E402
from backend import risk as risk_engine  # noqa: E402
from backend import live_track as live_tracker  # noqa: E402
from backend import sensors as sensor_feed  # noqa: E402
from backend import alerts as alert_engine  # noqa: E402
from backend import auth as auth_engine  # noqa: E402
from backend import predict as predict_engine  # noqa: E402
from backend import behavior_stats as behavior_engine  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

def _jobs_path() -> Path:
    p = Path(os.environ.get("AQUA_BACKEND_DATA", ROOT / "backend" / "data")) / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p

class _JobsProxy:
    def __getattr__(self, name):
        return getattr(_jobs_path(), name)
    def __truediv__(self, other):
        return _jobs_path() / other
    def __fspath__(self):
        return str(_jobs_path())
    def __str__(self):
        return str(_jobs_path())
    def __repr__(self):
        return repr(_jobs_path())

JOBS = _JobsProxy()
MAX_UPLOAD_MB = int(os.environ.get("AQUA_MAX_UPLOAD_MB", 500))
MAX_FRAMES = int(os.environ.get("AQUA_MAX_FRAMES", 9000))   # ~5 min at 30 fps; one GPU job at a time
ORIGINS = os.environ.get("AQUA_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ID_RE = re.compile(r"^[0-9a-f]{32}$")


def vision_backend():
    """Which detection backend serves video analysis + live detection.

    Priority: explicit AQUA_VISION_BACKEND ("api"|"yolo") wins; otherwise the
    configured LLM API keys select "api" (Groq vision primary, Gemini vision
    fallback); otherwise local weights when present, else "yolo" (which then
    fails closed with a clear 503). Training files are never touched by this
    selection — "yolo" remains available via explicit opt-in.

    Honest trade-off (kept visible, see backend/vision.py and eval_detection.json):
    the local tilapia_seg weights measured F1 0.9577 @ IoU 0.5 on 896 labeled
    test images from independent session GX010206, while API vision output is
    zero-shot and unevaluated on tilapia footage (boxes only, no masks,
    model-estimated scores). API-first is the operator's explicit choice.
    """
    explicit = os.environ.get("AQUA_VISION_BACKEND", "").strip().lower()
    if explicit in ("api", "yolo"):
        return explicit
    v = api_vision.status()
    if v["groq_configured"] or v["gemini_configured"]:
        return "api"
    if Path(sm.DETECTOR).is_file():
        return "yolo"
    return "yolo"

_lock = threading.RLock()   # job.json is replaced atomically; reads and writes must not interleave on Windows
_pool = ThreadPoolExecutor(max_workers=1)   # serialises GPU analyses


# ---------------------------------------------------------------- job store (job.json is the source of truth)
def _dir(job_id):
    if not ID_RE.match(job_id or ""):
        return None
    d = JOBS / job_id
    return d if d.is_dir() else None


def _read(d):
    with _lock:
        return json.loads((d / "job.json").read_text(encoding="utf-8"))


def _write(d, job):
    with _lock:
        tmp = d / "job.json.tmp"
        tmp.write_text(json.dumps(job), encoding="utf-8")
        tmp.replace(d / "job.json")


def _err(status, message):
    return JSONResponse({"error": message}, status_code=status)


def _clean_name(name):
    return re.sub(r"[^\w.\- ]", "_", os.path.basename(name or "video"))[:120] or "video"


def _looks_like_video(head: bytes, ext: str) -> bool:
    if ext in {".mp4", ".mov"}:
        return head[4:8] == b"ftyp"
    if ext == ".avi":
        return head[:4] == b"RIFF" and head[8:12] == b"AVI "
    return head[:4] == b"\x1a\x45\xdf\xa3"   # mkv / webm (EBML)


# ---------------------------------------------------------------- endpoints
async def health(_):
    model = Path(sm.DETECTOR)
    llm_status = llm.status()
    vb = vision_backend()
    vstat = api_vision.status()
    vision_ready = (model.is_file() if vb == "yolo"
                    else (vstat["groq_configured"] or vstat["gemini_configured"]))
    return JSONResponse({
        "status": "ok", "model_available": vision_ready, "model_validated": False,
        "note": "Detection quality is not validated for new tanks, lighting or camera angles.",
        "vision_backend": vb,
        "llm": {"groq_configured": llm_status["groq_configured"], "gemini_configured": llm_status["gemini_configured"]},
    })


async def upload(request: Request):
    if int(request.headers.get("content-length") or 0) > (MAX_UPLOAD_MB + 1) * 1024 * 1024:
        return _err(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
    form = await request.form()
    f = form.get("file")
    if f is None or not hasattr(f, "read"):
        return _err(400, "Send the video as multipart field 'file'.")
    ext = Path(f.filename or "").suffix.lower()
    if ext not in EXTS:
        return _err(415, f"Unsupported file type. Use {', '.join(sorted(EXTS))}.")
    job_id = uuid.uuid4().hex
    d = JOBS / job_id
    d.mkdir(parents=True)
    video = d / f"video{ext}"
    size, limit = 0, MAX_UPLOAD_MB * 1024 * 1024

    def reject(status, msg):
        for p in d.glob("*"):
            p.unlink()
        d.rmdir()
        return _err(status, msg)

    with video.open("wb") as out:
        while chunk := await f.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                return reject(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
            out.write(chunk)
    if size == 0:
        return reject(422, "The file is empty.")
    with video.open("rb") as fh:
        head = fh.read(16)
    if not _looks_like_video(head, ext):
        return reject(415, "File content does not match its video extension.")
    cap = cv2.VideoCapture(str(video))
    fps, frames = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok = cap.isOpened() and cap.read()[0]
    cap.release()
    if not ok or not fps or fps <= 0:
        return reject(422, "The video could not be decoded, or its frame rate is unavailable.")
    if frames > MAX_FRAMES:
        return reject(422, f"Video has {frames} frames; the limit is {MAX_FRAMES}.")
    _write(d, {"id": job_id, "filename": _clean_name(f.filename), "state": "uploaded", "video": video.name,
               "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"), "error": None})
    return JSONResponse({"jobId": job_id, "videoId": job_id, "status": "uploaded"})


async def start(request: Request):
    try:
        job_id = (await request.json()).get("videoId")
    except Exception:
        return _err(400, "Send JSON: {\"videoId\": \"...\"}.")
    d = _dir(job_id)
    if d is None:
        return _err(404, "Unknown video id.")
    if vision_backend() == "api":
        v = api_vision.status()
        if not (v["groq_configured"] or v["gemini_configured"]):
            return _err(503, "API vision backend selected but no LLM key is configured. "
                             "Set GROQ_API_KEY and/or GEMINI_API_KEY, or set AQUA_VISION_BACKEND=yolo.")
    elif not Path(sm.DETECTOR).is_file():
        return _err(503, "Model weights are not available on the server.")
    with _lock:
        job = _read(d)
        if job["state"] not in ("uploaded", "failed"):   # failed jobs may be retried; others are never re-run
            return _err(409, f"Analysis already {job['state']}.")
        job.update(state="queued", error=None)
        _write(d, job)
    _pool.submit(_run, d)
    return JSONResponse({"jobId": job_id, "status": "queued"}, status_code=202)


async def status(request: Request):
    d = _dir(request.path_params["job_id"])
    if d is None:
        return _err(404, "Unknown job.")
    j = _read(d)
    return JSONResponse({"jobId": j["id"], "state": j["state"], "error": j["error"], "filename": j["filename"], "createdAt": j["createdAt"]})


async def results(request: Request):
    d = _dir(request.path_params["job_id"])
    if d is None:
        return _err(404, "Unknown job.")
    j = _read(d)
    if j["state"] != "completed":
        return _err(409, j["error"] or f"Analysis is {j['state']}; results are not available.")
    return JSONResponse(json.loads((d / "result.json").read_text(encoding="utf-8")))


async def frame(request: Request):
    d = _dir(request.path_params["job_id"])
    kind = request.path_params["kind"]
    if d is None or kind not in ("original", "annotated") or not (d / f"{kind}.jpg").is_file():
        return _err(404, "Frame not available.")
    return FileResponse(d / f"{kind}.jpg", media_type="image/jpeg")


# ---------------------------------------------------------------- live single-frame detection
MAX_FRAME_BYTES = 3 * 1024 * 1024
_live_lock = threading.Lock()
_live_model = None


def _env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_flag(name, default_on=True):
    raw = os.environ.get(name)
    if raw is None:
        return default_on
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def live_conf():
    """YOLO conf for live frames. AQUA_LIVE_CONF_MIN (default 0.35) is a floor for
    the live path only; recorded video keeps sm.CONF untouched.
    Rollback to the old live behavior: AQUA_LIVE_CONF_MIN=0."""
    return min(1.0, max(_env_float("AQUA_CONF", 0.20), _env_float("AQUA_LIVE_CONF_MIN", 0.35)))


def live_weights():
    from pathlib import Path as _P
    return os.environ.get("AQUA_DETECTOR_WEIGHTS", str(sm.DETECTOR))


def tile_trigger():
    return _env_float("AQUA_TILE_TRIGGER", 0.25)


def edge_min():
    return _env_float("AQUA_EDGE_MIN", 0.10)


def live_engine():
    """AQUA_LIVE_ENGINE=friend|world|florence (default friend = trained best.pt
    path, unchanged). Unknown values fall back to friend: a bad env var must
    never take the live view down. Rollback is the same one-liner."""
    e = os.environ.get("AQUA_LIVE_ENGINE", "friend").strip().lower()
    return e if e in ("friend", "world", "florence") else "friend"


def max_fishes():
    """AQUA_MAX_FISHES: maximum fish present in the monitored tank (default 2).
    Excess detections beyond this limit are rejected by confidence ranking."""
    try:
        raw = os.environ.get("AQUA_MAX_FISHES")
        if raw is not None:
            v = int(raw)
            if v > 0:
                return v
    except (TypeError, ValueError):
        pass
    return 2


_STARTUP_LOGGED = False


def _log_startup():
    global _STARTUP_LOGGED
    if _STARTUP_LOGGED:
        return
    _STARTUP_LOGGED = True
    print(f"[aqua] live detector weights={live_weights()} conf={live_conf()} "
          f"tile_trigger={tile_trigger()} edge_min={edge_min()} "
          f"engine={live_engine()} "
          f"motion_gate={_env_flag('AQUA_MOTION_GATE', True)}", flush=True)


def _thin(points, limit=80):
    step = max(1, -(-len(points) // limit))   # ceiling, so at most `limit` points
    return [[round(x, 4), round(y, 4)] for x, y in points[::step]]


# ---------------------------------------------------------------- live-detection sanity (true fish boundaries)
# Limits grounded in the project's own tilapia annotations (dataset/tilapia_yolo,
# train 7,669 boxes / test 6,604 boxes, max 11 fish/frame, measured Oct 2026):
# single-fish box area max 0.51 (train) / 0.275 (test), p99 0.287, p99.9 0.40.
# New adaptive rule (HANDOFF T3): span >= 0.97 or area > 0.80 is physically
# implausible for one fish -> reject. Area in (0.40, 0.80] is kept ONLY when
# edge-rich (textured, per predict_tiled.adaptive_sanitize) and tagged
# large_closeup=true so the UI/count tile can decide; edge-poor ones are
# rejected WITH the flag and the measured edge value (never silently dropped).
# Measured edge densities: flat gray 0.00, whole-tank garbage 0.075-0.11,
# tank slabs 0.12-0.20, small fish boxes 0.12-0.29 — slabs overlap the fish
# range, so AQUA_EDGE_MIN=0.10 is a compromise (see probe_edges.py numbers),
# and the live-domain eval gate (recall/FP) is the real judge.
LIVE_BOX_MAX_FRAC = 0.40    # adaptive boundary: above this needs texture evidence
LIVE_HARD_MAX_FRAC = 0.80   # single box above this is never one fish -> reject
LIVE_MASK_MAX_FRAC = 0.61   # single mask above max annotated union of ALL fish -> reject
LIVE_MASK_DEDUP_IOU = 0.60  # overlapping masks above this keep the higher confidence only
LIVE_BOX_DEDUP_IOU = 0.50   # overlapping boxes above this keep the higher confidence only
LIVE_FULL_SPAN_FRAC = 0.97  # box spanning >=97% of width or height -> tank band, reject
LIVE_MIN_AREA_FRAC = 0.0002  # sliver rejection (normalised coords)
LIVE_UNION_REVIEW_FRAC = 0.61  # accepted union above this -> frame flagged for review


def _box_iou(a, b):
    """IoU of two normalised [x1,y1,x2,y2] boxes."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    aa = max(0.0, (a[2] - a[0])) * max(0.0, (a[3] - a[1]))
    bb = max(0.0, (b[2] - b[0])) * max(0.0, (b[3] - b[1]))
    union = aa + bb - inter
    return inter / union if union > 0 else 0.0


def _poly_area_frac(poly):
    """Shoelace area of an Nx2 normalised polygon as a frame fraction."""
    x, y = np.asarray(poly, dtype=np.float64)[:, 0], np.asarray(poly, dtype=np.float64)[:, 1]
    if len(x) < 3 or not np.isfinite(x).all() or not np.isfinite(y).all():
        return 0.0
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))) / 2.0


def _mask_iou(a, b, size=128):
    """Mask IoU of two normalised polygons via small-raster rasterisation."""
    ma = np.zeros((size, size), np.uint8)
    mb = np.zeros((size, size), np.uint8)
    for m, p in ((ma, a), (mb, b)):
        pts = np.clip(np.round(np.asarray(p, dtype=np.float64) * size), 0, size - 1).astype(np.int32)
        if len(pts) >= 3:
            cv2.fillPoly(m, [pts], 1)
    inter = int(np.logical_and(ma, mb).sum())
    union = int(np.logical_or(ma, mb).sum())
    return inter / union if union else 0.0


def _sanitize_live_detections(dets):
    """Split raw frame detections into (accepted, rejected).

    Every accepted detection has finite coordinates clipped to the frame, a valid
    non-sliver box, and — when a mask outline is present — a fish-plausible mask:
    no duplicates of a higher-confidence mask and no mask larger than any
    annotated single-fish region. Rejected entries keep {box, confidence, reason}.
    """
    cleaned = []
    for d in dets or []:
        try:
            x1, y1, x2, y2 = (float(v) for v in d["box"])
            conf = float(d.get("confidence", 0.5))
        except (TypeError, ValueError, KeyError):
            continue
        if not all(np.isfinite([x1, y1, x2, y2, conf])):
            continue
        x1, y1 = max(0.0, min(x1, x2)), max(0.0, min(y1, y2))
        x2, y2 = min(1.0, max(x1, x2)), min(1.0, max(y1, y2))
        box_area = (x2 - x1) * (y2 - y1)
        if box_area < LIVE_MIN_AREA_FRAC:
            continue  # sliver: not a fish, not worth a diagnostic
        outline = None
        if isinstance(d.get("outline"), list) and len(d["outline"]) > 2:
            pts = []
            for p in d["outline"]:
                try:
                    fx, fy = float(p[0]), float(p[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if np.isfinite(fx) and np.isfinite(fy):
                    pts.append([min(1.0, max(0.0, fx)), min(1.0, max(0.0, fy))])
            if len(pts) > 2 and _poly_area_frac(pts) >= LIVE_MIN_AREA_FRAC:
                outline = [[round(x, 4), round(y, 4)] for x, y in pts]
        entry = {"box": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                 "confidence": round(min(1.0, max(0.0, conf)), 3),
                 **({"outline": outline} if outline else {}),
                 "_mask_area": _poly_area_frac(outline) if outline else 0.0}
        if isinstance(d.get("source"), str):
            entry["source"] = d["source"]
        try:
            e = float(d.get("edges"))
            if np.isfinite(e):
                entry["edges"] = round(e, 4)
        except (TypeError, ValueError):
            pass
        cleaned.append(entry)
    # box dedup: overlapping boxes keep the higher confidence only (tank slabs
    # overlap each other heavily; without this one water band becomes N "fish")
    rejected = []
    deduped = []
    for d in sorted(cleaned, key=lambda d: -d["confidence"]):
        dup = any(_box_iou(d["box"], k["box"]) >= LIVE_BOX_DEDUP_IOU for k in deduped)
        if dup:
            rejected.append({k: d[k] for k in ("box", "confidence") if k in d} | {"reason": "duplicate_box"})
        else:
            deduped.append(d)
    # mask dedup: overlapping masks keep the higher confidence only
    kept = []
    for d in deduped:
        dup = False
        if d["_mask_area"] > 0:
            for k in kept:
                if k["_mask_area"] > 0 and _mask_iou(d.get("outline", []), k.get("outline", [])) >= LIVE_MASK_DEDUP_IOU:
                    dup = True
                    break
        if dup:
            rejected.append({k: d[k] for k in ("box", "confidence") if k in d} | {"reason": "duplicate_mask"})
        else:
            kept.append(d)
    accepted, union = [], 0.0
    import logging as _logging
    _slog = _logging.getLogger("aqua.sanitize")
    for d in kept:
        box_area = (d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1])
        span_x, span_y = d["box"][2] - d["box"][0], d["box"][3] - d["box"][1]
        if span_x >= LIVE_FULL_SPAN_FRAC or span_y >= LIVE_FULL_SPAN_FRAC:
            rej = {k: d[k] for k in ("box", "confidence") if k in d} | {"reason": "full_span_implausible"}
            rejected.append(rej)
            _slog.debug("reject full_span box=%s area=%.3f", d["box"], box_area)
        elif d["_mask_area"] > LIVE_MASK_MAX_FRAC:
            rejected.append({k: d[k] for k in ("box", "confidence") if k in d} | {"reason": "mask_area_implausible"})
            _slog.debug("reject mask_area box=%s mask=%.3f", d["box"], d["_mask_area"])
        elif box_area > LIVE_HARD_MAX_FRAC:
            rejected.append({k: d[k] for k in ("box", "confidence") if k in d} | {"reason": "box_area_implausible"})
            _slog.debug("reject hard_max box=%s area=%.3f", d["box"], box_area)
        elif box_area > LIVE_BOX_MAX_FRAC:
            # Adaptive branch: keep only with texture evidence; never silently
            # drop — the flag + measured edges travel with the decision.
            edges = d.get("edges")
            if edges is not None and edges >= edge_min():
                entry = {k: d[k] for k in ("box", "confidence", "outline", "source") if k in d}
                entry["large_closeup"] = True
                accepted.append(entry)
                union += d["_mask_area"]
                _slog.debug("accept large_closeup box=%s area=%.3f edges=%.3f", d["box"], box_area, edges)
            else:
                rej = {k: d[k] for k in ("box", "confidence") if k in d} | {
                    "reason": "box_area_implausible", "large_closeup": True}
                if edges is not None:
                    rej["edges"] = edges
                rejected.append(rej)
                _slog.debug("reject large_flat box=%s area=%.3f edges=%s", d["box"], box_area, edges)
        else:
            entry = {k: d[k] for k in ("box", "confidence", "outline", "source") if k in d}
            if d.get("source") == "tile":
                entry["source"] = "tile"
            union += d["_mask_area"]
            accepted.append(entry)
    # Cap to max fish present in tank (user has at most 2 fish)
    max_f = max_fishes()
    if len(accepted) > max_f:
        accepted.sort(key=lambda d: -float(d.get("confidence", 0.0)))
        for extra in accepted[max_f:]:
            rej = {k: extra[k] for k in ("box", "confidence") if k in extra} | {"reason": "exceeds_max_fish_cap"}
            rejected.append(rej)
        accepted = accepted[:max_f]
    review = None
    if rejected:
        reasons = {}
        for r in rejected:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        review = (f"{len(rejected)} candidate(s) rejected ({'; '.join(f'{n} {k}' for k, n in reasons.items())}); "
                  "rejected regions are preserved in `rejected`, not displayed as fish.")
    if union > LIVE_UNION_REVIEW_FRAC:
        review = ((review + " " if review else "") +
                  f"Accepted mask union covers {union:.0%} of the frame (annotated maximum {LIVE_UNION_REVIEW_FRAC:.0%}); treat as needs review.")
    return accepted, rejected, review


_live_model_path = None


def junk_geom_on():
    """G1: AQUA_JUNK_GEOM=1 enables the conservative geometry filter (default off)."""
    return _env_flag("AQUA_JUNK_GEOM", False)


def _junk_geometry(box):
    """G1 geometry rule, measured on eval_ab/conf_floor (13 frames, 29 boxes).

    Conservative on purpose: it removes only shell-like vertical blobs
    (aspect < 1.1 with area > 2% - both fish_tank shell boxes), full-frame
    blobs (>30% area) and thin full-width slivers. Measured effect when enabled:
    2/29 boxes removed, both junk shells (junk 11 -> 9; 18/18 real fish kept).
    This is NOT enough to reach the <=15% junk target, so the flag stays off by
    default and the Pareto table is reported in FINAL_PROJECT_REPORT.md.
    """
    try:
        x1, y1, x2, y2 = [float(v) for v in box]
    except (TypeError, ValueError):
        return "bad_box"
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return "degenerate"
    area = w * h
    if area > 0.30:
        return "full_frame_blob"
    if h < 0.02 and w > 0.30:
        return "sliver"
    if area > 0.02 and w / h < 1.1:
        return "vertical_blob"
    return None


def _live_predict(img):
    """Adaptive live detection on one frame (T2): single pass first, tiled
    escalation only when weak. Boxes/outlines are normalised 0-1. Weights and
    conf come from AQUA_DETECTOR_WEIGHTS / AQUA_CONF (rollback: point the env
    back at the old best.pt, no code edit). AQUA_LIVE_ENGINE=world|florence
    switches to the zero-shot engines (backend/live_detect/zero_shot.py) in the
    same output contract; sanitizer, tracker and UI are untouched."""
    global _live_model, _live_model_path
    import torch
    _log_startup()
    engine = live_engine()
    if engine != "friend":
        from backend.live_detect import predict_tiled as pt
        from backend.live_detect import zero_shot
        t0 = time.perf_counter()
        try:
            raw = {"world": zero_shot.detect_world,
                   "florence": zero_shot.detect_florence}[engine](img)
        except zero_shot.EngineUnavailable as e:
            raise RuntimeError(f"{engine} engine unavailable: {e}") from e
        ms = round((time.perf_counter() - t0) * 1000)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        dets = [{"box": d["box"], "confidence": d["confidence"], "source": engine,
                 "edges": round(pt.edge_density(gray, d["box"]), 4),
                 **({"outline": d["outline"]} if d.get("outline") else {})}
                for d in raw]
        extra = {}
        if junk_geom_on():
            kept, geom_rejected = [], []
            for d in dets:
                reason = _junk_geometry(d["box"])
                if reason:
                    geom_rejected.append({"box": d["box"], "confidence": d["confidence"], "reason": reason})
                else:
                    kept.append(d)
            dets = kept
            extra = {"geometryRejected": geom_rejected, "junkGeom": True}
        return {"detections": dets, "count": len(dets), "inferenceMs": ms,
                "vision": {"backend": "yolo", "provider": "zero-shot", "model": engine}, **extra}
    path = live_weights()
    from backend.live_detect import predict_tiled as pt
    with _live_lock:
        if _live_model is None or _live_model_path != path:
            from ultralytics import YOLO
            _live_model = YOLO(path)
            _live_model_path = path
        t0 = time.perf_counter()
        raw = pt.detect_adaptive(
            _live_model, img, conf=live_conf(), trigger=tile_trigger(),
            imgsz=640, mode="auto",
            device=0 if torch.cuda.is_available() else "cpu")
        ms = round((time.perf_counter() - t0) * 1000)
    dets = []
    for d in raw:
        out = {"box": d["box"], "confidence": d["conf"], "source": d["source"],
               "edges": d.get("edges", 0.0)}
        if d.get("outline"):
            out["outline"] = d["outline"]
        dets.append(out)
    return {"detections": dets, "count": len(dets), "inferenceMs": ms}


def _detect_frame(img, vb):
    """Run one frame through the selected backend and sanitize detections.

    Shared by /api/live/detect (stateless) and /api/live/track (stateful).
    Returns the response dict with accepted `detections`/`count` plus optional
    `rejected` diagnostics and `review` flag. Never raises for bad geometry —
    sanitization only filters; model errors still propagate.
    """
    out = _live_predict_api(img) if vb == "api" else _live_predict(img)
    accepted, rejected, review = _sanitize_live_detections(out.get("detections"))
    out["detections"], out["count"] = accepted, len(accepted)
    if rejected:
        out["rejected"] = rejected
    if review:
        out["review"] = review
    return out


def live_fallback_on():
    """AQUA_LIVE_ALLOW_FALLBACK=1: on cloud failure run local YOLO once (labeled).
    Default 0: degrade to zero detections with an amber reason (never a 500)."""
    return _env_flag("AQUA_LIVE_ALLOW_FALLBACK", False)


def _safe_error_text(e):
    msg = getattr(e, "message", None) or f"{type(e).__name__}: {e}"
    return re.sub(r"[A-Za-z]:[\\/][^\s'\"]*", "<path>", str(msg))[:300]


def _degraded_frame_result(img, err):
    """API vision down (B1): HTTP 200 with zero detections + degraded flag, so the
    UI shows an amber badge instead of a generic error. With
    AQUA_LIVE_ALLOW_FALLBACK=1 (B2) local YOLO runs once and is labeled
    visionBackend="yolo-fallback(api-down)"."""
    reason = _safe_error_text(err)
    if live_fallback_on():
        try:
            out = _detect_frame(img, "yolo")
            out.update(visionBackend="yolo-fallback(api-down)", degraded=True, degradedReason=reason)
            return out
        except Exception as fe:
            reason = (reason + " | yolo fallback failed: " + _safe_error_text(fe))[:300]
    return {"detections": [], "count": 0, "inferenceMs": 0,
            "visionBackend": "api", "degraded": True, "degradedReason": reason,
            "vision": {"backend": "api", "provider": None, "model": None}}


# ---------------------------------------------------------------- live captures (D)
LIVE_CAPTURE_DIR = ROOT / "dataset" / "live_captures"
LIVE_CAPTURE_MAX = int(os.environ.get("AQUA_LIVE_CAPTURE_MAX", 2000))
_capture_lock = threading.Lock()
_capture_last = {}   # session -> epoch seconds of the last saved pair


def _live_capture_on():
    """AQUA_LIVE_CAPTURE=0 disables saving live frames (default on: builds the
    offline eval set; processed frame + detections JSON, capped, oldest first)."""
    return _env_flag("AQUA_LIVE_CAPTURE", True)


def _prune_captures():
    """Keep at most LIVE_CAPTURE_MAX capture pairs; delete the oldest first.
    Caller holds _capture_lock."""
    try:
        files = sorted(LIVE_CAPTURE_DIR.rglob("*.jpg"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for p in files[:max(0, len(files) - LIVE_CAPTURE_MAX)]:
        try:
            p.unlink()
            p.with_suffix(".json").unlink(missing_ok=True)
        except OSError:
            pass


def _maybe_capture(session, jpeg_body, out):
    """Save one PROCESSED frame + detections JSON per session per interval (D).

    The body is the frame the client actually sent (already rotated/cropped),
    so captures match production input. Failures never affect the response.
    """
    if not _live_capture_on():
        return
    now = time.time()
    with _capture_lock:
        if now - _capture_last.get(session, 0.0) < _env_float("AQUA_LIVE_CAPTURE_EVERY_S", 30.0):
            return
        try:
            d = LIVE_CAPTURE_DIR / time.strftime("%Y-%m-%d", time.localtime(now))
            d.mkdir(parents=True, exist_ok=True)
            stem = time.strftime("%H%M%S", time.localtime(now)) + f"-{int(now * 1000) % 1000:03d}"
            (d / f"{stem}.jpg").write_bytes(jpeg_body)
            (d / f"{stem}.json").write_text(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "session": session,
                "visionBackend": out.get("visionBackend"),
                "degraded": out.get("degraded", False),
                "degradedReason": out.get("degradedReason"),
                "count": out.get("count"),
                "detections": out.get("detections", []),
                "tracks": out.get("tracks", []),
                "movement": out.get("movement"),
                "validated": False,
            }, default=str), encoding="utf-8")
            _capture_last[session] = now
            _prune_captures()
        except OSError:
            _capture_last.pop(session, None)  # disk issue: retry on a later frame, never break the stream


async def live_detect(request: Request):
    """Body: one JPEG/PNG frame. Returns frame-level detections only: no tracking, no unique-fish count, no validation."""
    vb = vision_backend()
    if vb == "api":
        v = api_vision.status()
        if not (v["groq_configured"] or v["gemini_configured"]):
            return _err(503, "API vision backend selected but no LLM key is configured.")
    elif not Path(sm.DETECTOR).is_file():
        return _err(503, "Model weights are not available on the server.")
    if int(request.headers.get("content-length") or 0) > MAX_FRAME_BYTES:
        return _err(413, "Frame is too large.")
    body = await request.body()
    if not body:
        return _err(400, "Send one image frame as the request body.")
    if len(body) > MAX_FRAME_BYTES:
        return _err(413, "Frame is too large.")
    img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return _err(415, "The frame could not be decoded as an image.")
    try:
        out = await run_in_threadpool(_detect_frame, img, vb)
    except llm.LlmError as e:
        if vb != "api":
            return _err(500, _safe_error_text(e))
        out = _degraded_frame_result(img, e)   # B1: cloud down = 200 + empty + degraded, never a bare 500
    except Exception as e:
        return _err(500, re.sub(r"[A-Za-z]:[\\/][^\s'\"]*", "<path>", f"{type(e).__name__}: {e}")[:300])
    out.setdefault("visionBackend", "api" if vb == "api" else "yolo")
    out.setdefault("degraded", False)
    out.setdefault("degradedReason", None)
    out.update(timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), validated=False,
               note=("Frame-level API vision detections (Groq/Gemini, boxes only, scores model-estimated). "
                     "Not tracked, not unique fish, quality not validated for this camera.")
               if vb == "api" else
               "Frame-level detections from the existing weights. Not tracked, not unique fish, quality not validated for this camera.")
    return JSONResponse(out)


def _live_predict_api(img):
    """API vision replacement for _live_predict: boxes only, no mask outlines."""
    t0 = time.perf_counter()
    out = api_vision.detect_image(img)
    ms = round((time.perf_counter() - t0) * 1000)
    return {"detections": [{"box": d["box"], "confidence": d["confidence"]} for d in out["detections"]],
            "count": len(out["detections"]), "inferenceMs": ms,
            "vision": {"backend": "api", "provider": out["provider"], "model": out["model"]}}


SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


async def live_track(request: Request):
    """POST /api/live/track?session=<id> with one JPEG/PNG frame body.

    Stateful live tracking: the accepted detections of this frame are folded
    into the session's greedy centroid tracks, and per-track speeds plus a
    session movement summary are returned. Track ids are session-local, speeds
    are approximate at ~1 fps sampling, and camera-motion compensation is
    unavailable at this rate — all labeled in the response, never hidden.
    """
    vb = vision_backend()
    if vb == "api":
        v = api_vision.status()
        if not (v["groq_configured"] or v["gemini_configured"]):
            return _err(503, "API vision backend selected but no LLM key is configured.")
    elif not Path(sm.DETECTOR).is_file():
        return _err(503, "Model weights are not available on the server.")
    session = request.query_params.get("session") or ""
    if not SESSION_RE.match(session):
        return _err(422, "Provide a session id as ?session=<letters, digits, '-' or '_' up to 64 chars>.")
    if int(request.headers.get("content-length") or 0) > MAX_FRAME_BYTES:
        return _err(413, "Frame is too large.")
    body = await request.body()
    if not body:
        return _err(400, "Send one image frame as the request body.")
    if len(body) > MAX_FRAME_BYTES:
        return _err(413, "Frame is too large.")
    img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return _err(415, "The frame could not be decoded as an image.")
    try:
        out = await run_in_threadpool(_detect_frame, img, vb)
    except llm.LlmError as e:
        if vb != "api":
            return _err(500, _safe_error_text(e))
        out = _degraded_frame_result(img, e)   # B1: keep the session alive with an honest empty frame
    except Exception as e:
        return _err(500, re.sub(r"[A-Za-z]:[\\/][^\s'\"]*", "<path>", f"{type(e).__name__}: {e}")[:300])
    try:
        now = time.time()
        tr = await run_in_threadpool(live_tracker.update, session, img, out["detections"], now)
        for expired in await run_in_threadpool(live_tracker.sweep, now):
            history.record("live_session", status="expired", **expired)
    except Exception as e:
        return _err(500, re.sub(r"[A-Za-z]:[\\/][^\s'\"]*", "<path>", f"{type(e).__name__}: {e}")[:300])
    out.update(tr)
    try:
        behavior_engine.observe(tr.get("tracks"), img.shape[1], img.shape[0], now)
    except Exception:
        pass
    out.setdefault("visionBackend", "api" if vb == "api" else "yolo")
    out.setdefault("degraded", False)
    out.setdefault("degradedReason", None)
    _maybe_capture(session, body, out)
    out.update(timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), validated=False,
               note=("Live tracked detections (Groq/Gemini boxes, session-local track ids, approximate speeds). "
                     "Quality not validated for this camera.")
               if vb == "api" else
               "Live tracked detections from the existing weights (session-local track ids, approximate speeds). "
               "Quality not validated for this camera.")
    return JSONResponse(out)


# ---------------------------------------------------------------- LLM advice (Groq primary, Gemini fallback)
async def llm_status(_):
    return JSONResponse(llm.status())


async def vision_status(_):
    s = api_vision.status()
    s["backend"] = vision_backend()
    return JSONResponse(s)


TRACK_SUMMARY_CSV = ROOT / "fish_track_quality_summary_corrected.csv"


def _load_tracks(limit=200):
    import csv
    if not TRACK_SUMMARY_CSV.is_file():
        return None
    out = []
    with TRACK_SUMMARY_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                row["track_id"] = int(float(row.get("track_id") or 0))
                row["observations"] = int(float(row.get("observations") or 0))
            except (TypeError, ValueError):
                continue
            out.append(row)
            if len(out) >= limit:
                break
    out.sort(key=lambda r: -r["observations"])
    return out


async def list_tracks(_):
    tracks = await run_in_threadpool(_load_tracks)
    if tracks is None:
        return _err(404, "No track summary file. Run the tracking review pipeline first.")
    keep = ["track_id", "observations", "duration_sec", "mean_speed_px_sec", "median_speed_px_sec",
            "max_valid_speed_px_sec", "tracking_gaps", "missing_frames", "suspicious_jumps",
            "coverage_pct", "review_tracking", "review_reasons", "fps_used"]
    return JSONResponse({"tracks": [{k: t.get(k) for k in keep} for t in tracks]})


async def behavior(request: Request):
    """POST {"track_id": 1} -> LLM movement observation (replaces the RandomForest classifier).

    Also accepts {"track": {...}} with inline track statistics (live session tracks),
    validated below. Either way the observation is experimental and never enters risk.
    """
    try:
        payload = await request.json()
    except Exception:
        return _err(400, "Send JSON: {\"trackId\": <track id>} or {\"track_id\": <track id>}.")
    if not isinstance(payload, dict):
        return _err(400, "Send JSON: {\"trackId\": <track id>} or {\"track_id\": <track id>}.")
    tid = payload.get("trackId", payload.get("track_id"))
    try:
        tid = int(tid) if tid is not None else None
    except (TypeError, ValueError):
        return _err(422, "Provide a numeric trackId.")
    if tid is None and isinstance(payload.get("track"), dict):
        track, err = _coerce_inline_track(payload["track"])
        if err is not None:
            return err
    else:
        if tid is None:
            return _err(422, "Provide a numeric trackId or an inline track object.")
        tracks = await run_in_threadpool(_load_tracks, 5000)
        if tracks is None:
            return _err(404, "No track summary file. Run the tracking review pipeline first.")
        track = next((t for t in tracks if t.get("track_id") == tid), None)
        if track is None:
            return _err(404, "Unknown track id.")
        tid = track.get("track_id")
    try:
        out = await run_in_threadpool(llm.observe_behavior, track)
    except llm.NoKeysError as e:
        return _err(503, str(e))
    except llm.LlmError as e:
        return _err(502, str(e)[:600])
    out.update(track_id=tid, experimental=True,
               note="Experimental LLM movement observation. Not validated, not a health assessment.")
    return JSONResponse(out)


def _coerce_inline_track(raw):
    """Validate inline live-track stats into the shape llm.observe_behavior reads.

    Returns (track_dict, None) or (None, error_response). Rejects non-numeric,
    non-finite, or empty-observation input rather than inventing values.
    """
    import math as _math

    def _num(key, default=None, minimum=None):
        v = raw.get(key, default)
        if v is None:
            return default
        try:
            f = float(v)
        except (TypeError, ValueError):
            return "bad"
        if not _math.isfinite(f):
            return "bad"
        if minimum is not None and f < minimum:
            return "bad"
        return f

    obs = _num("observations", minimum=1)
    if obs == "bad" or obs is None:
        return None, _err(422, "Inline track needs observations >= 1.")
    dur = _num("duration_sec", default=0.0, minimum=0.0)
    mean_sp = _num("mean_speed_px_sec")
    med_sp = _num("median_speed_px_sec")
    max_sp = _num("max_valid_speed_px_sec")
    gaps = _num("tracking_gaps", default=0.0, minimum=0.0)
    missing = _num("missing_frames", default=0.0, minimum=0.0)
    for name, val in (("duration_sec", dur), ("mean_speed_px_sec", mean_sp),
                      ("median_speed_px_sec", med_sp), ("max_valid_speed_px_sec", max_sp),
                      ("tracking_gaps", gaps), ("missing_frames", missing)):
        if val == "bad":
            return None, _err(422, f"Inline track field '{name}' must be a finite number.")
    tid = raw.get("track_id", 0)
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        return None, _err(422, "Inline track field 'track_id' must be numeric.")
    return {"track_id": tid, "observations": int(obs),
            "duration_sec": dur, "fps_used": raw.get("fps_used", "live ~1fps"),
            "mean_speed_px_sec": mean_sp, "median_speed_px_sec": med_sp,
            "max_valid_speed_px_sec": max_sp, "tracking_gaps": gaps,
            "missing_frames": missing,
            "suspicious_jumps": _num("suspicious_jumps", default=0.0, minimum=0.0),
            "coverage_pct": _num("coverage_pct"),
            "review_tracking": bool(raw.get("review_tracking", int(obs) < 30)),
            "review_reasons": str(raw.get("review_reasons") or
                                  ("short track; live session-local identity" if int(obs) < 30
                                   else "live session-local identity")),
            "source": "live_session"}, None


async def advice(request: Request):
    """POST {"tankId": "...", "jobId": "..."} -> plain-language explanation of the
    already-computed rule-based assessment. The LLM never changes the water risk."""
    combined, err = await _combined_from_request(request)
    if err is not None:
        return err
    try:
        out = await run_in_threadpool(llm.advise, combined)
    except llm.NoKeysError as e:
        return _err(503, str(e))
    except llm.LlmError as e:
        return _err(502, str(e)[:600])
    out.update(waterRisk=((combined.get("water") or {}).get("waterRisk")),
               overallStatus=combined.get("overallStatus"))
    return JSONResponse(out)


async def _combined_from_request(request: Request):
    """Shared validation + combined-assessment builder for advice/risk/explanation.

    Returns (combined_dict, None) or (None, error_response). combined_dict always
    carries _tankId/_jobId for history and explanation scope keys.
    """
    try:
        payload = await request.json()
    except Exception:
        return None, _err(400, "Send a JSON body: {\"tankId\": \"...\", \"jobId\": \"...\"} (jobId optional).")
    if not isinstance(payload, dict):
        return None, _err(400, "Send a JSON body: {\"tankId\": \"...\", \"jobId\": \"...\"} (jobId optional).")
    tank = (payload.get("tankId") or "").strip()
    job = payload.get("jobId") or None
    if tank and not water.NAME_RE.match(tank):
        return None, _err(422, "Invalid tankId.")
    if job and not ID_RE.match(job):
        return None, _err(422, "Invalid jobId.")
    if not tank and not job:
        return None, _err(422, "Provide at least a tankId (water screening) or a jobId (video).")
    records, _ = water.read_all()
    assessed = water.assess_water(water.current_records(records, tank), water.load_rules(), water._now()) if tank else None
    result, reason = _video_result(job) if job else (None, None)
    combined = water.combine(assessed, water.video_summary(result, reason))
    if assessed is None and not (combined["video"] or {}).get("available"):
        return None, _err(404, "No water readings for this tank and no analysed video attached.")
    combined["_tankId"], combined["_jobId"] = tank or None, job
    return combined, None


async def risk(request: Request):
    """POST {"tankId": "...", "jobId": "..."} -> unified 5-level operational risk
    (NORMAL/WATCH/WARNING/CRITICAL/INSUFFICIENT_DATA). Deterministic; see backend/risk.py."""
    combined, err = await _combined_from_request(request)
    if err is not None:
        return err
    doc = risk_engine.assess(combined)
    history.record("risk_assessment", tank_id=combined["_tankId"], job_id=combined["_jobId"],
                   status=doc["status"], engine=doc["engine"])
    return JSONResponse(doc)


def _evidence_for(combined, risk_doc):
    """Minimal structured evidence object for the LLM (§8.1): readings, assessments,
    quality flags, thresholds, limits. No credentials, no raw uploads."""
    w = (combined or {}).get("water") or {}
    v = (combined or {}).get("video") or {}
    readings = []
    for m in w.get("measurements", []):
        if m.get("dataQuality") == "missing" or m.get("value") is None:
            readings.append({"parameter": m.get("label"), "status": "not_measured"})
        else:
            readings.append({"parameter": m.get("label"), "value": m.get("value"),
                             "unit": m.get("unit"), "level": m.get("level"),
                             "quality": m.get("dataQuality"), "timestamp": m.get("timestamp")})
    return {
        "risk_status": risk_doc["status"],
        "water_risk": w.get("waterRisk"),
        "readings": readings,
        "triggered_rules": risk_doc.get("triggered_rules", []),
        "data_quality": (w.get("dataQuality") or {}),
        "video": {"available": v.get("available"), "reliability": v.get("reliability"),
                  "observations": (v.get("observations") or [])[:6]},
        "behavior": "experimental only; no validated classifier (see risk domains)",
        "uncertainty": (risk_doc.get("uncertainty", []) +
                        ["Thresholds provisional; confirm with a specialist."])[:6],
    }


async def explanation(request: Request):
    """POST {"tankId": "...", "jobId": "..."} -> structured Gemini explanation
    (JSON schema §8.2) with cache reuse + cooldown (§8.3). Never overrides risk."""
    combined, err = await _combined_from_request(request)
    if err is not None:
        return err
    doc = risk_engine.assess(combined)
    evidence = _evidence_for(combined, doc)
    scope = f"{combined['_tankId'] or '-'}:{combined['_jobId'] or '-'}"
    try:
        resp, cached = await run_in_threadpool(llm.explain_cached, scope, evidence)
    except llm.CooldownError as e:
        history.record("explanation", tank_id=combined["_tankId"], job_id=combined["_jobId"],
                       status="cooldown", retry_after_s=e.retry_after_s)
        return JSONResponse({"error": str(e), "retry_after_s": e.retry_after_s,
                             "last": e.last}, status_code=429)
    except llm.NoKeysError as e:
        return _err(503, str(e))
    except llm.LlmError as e:
        return _err(502, str(e)[:600])
    history.record("explanation", tank_id=combined["_tankId"], job_id=combined["_jobId"],
                   status="generated" if not cached else "cache_reused",
                   provider=resp.get("provider"), model=resp.get("model"),
                   risk_status=doc["status"])
    resp["risk_status"] = doc["status"]  # deterministic status travels with the text
    return JSONResponse(resp)


async def history_list(request: Request):
    """GET /api/history?limit=50&event=video_analysis -> newest-first genuine records."""
    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        return _err(422, "limit must be a number.")
    event = request.query_params.get("event") or None
    recs, skipped = history.query(limit=limit, event=event)
    return JSONResponse({"records": recs, "skippedLines": skipped})


# ---------------------------------------------------------------- analysis worker
def _run_api(d: Path, job: dict, t0: float):
    """Sampled API-vision analysis (replaces per-frame YOLO when vision_backend() == 'api').

    Same result.json shape as the YOLO path so the frontend works unchanged,
    plus a visionBackend block disclosing the API backend, sampling and limits.
    """
    import pandas as pd

    video = d / job["video"]
    rows, preview_bgr, preview_dets, info = api_analysis.analyze(video)
    s = api_analysis.summarize(rows)
    pd.DataFrame(rows).to_csv(d / "frames.csv", index=False)

    annotated = api_vision.draw_boxes(preview_bgr, preview_dets)
    cv2.imwrite(str(d / "original.jpg"), preview_bgr)
    cv2.imwrite(str(d / "annotated.jpg"), annotated)

    api_note = ("API vision mode (Groq vision primary, Gemini vision fallback): counts are approximate "
                "zero-shot box estimates — no segmentation masks, no tracking, scores are model-estimated "
                "and uncalibrated. Treat as indicative only.")
    base = f"/api/analyses/{job['id']}/frames"
    mid = rows[len(rows) // 2]
    result = {
        "videoName": job["filename"], "fps": info["fps"], "frames": info["frames_total"],
        "processingSec": round(time.perf_counter() - t0, 2),
        "visionBackend": {"backend": "api", "providers": info["providers"], "sampling": info["sampling"],
                          "fallback_used": info["fallback_used"], "masks": False},
        "detections": {"meanPerFrame": s["detections_mean"], "min": s["detections_min"], "max": s["detections_max"],
                       "framesWithoutDetection": s["frames_without_detection"],
                       "reliable": False, "reasons": [api_note]},
        "movement": {"reliable": False, "meanBoxAreaFrac": s["box_area_frac_mean"],
                     "countChangeRate": s["count_change_rate"],
                     "reasons": [api_note + " Camera motion is not estimated in API mode, so movement is a coarse count/box-area proxy."]},
        "preview": {"originalUrl": f"{base}/original", "annotatedUrl": f"{base}/annotated",
                    "timestampSec": float(mid["time_sec"]), "detections": len(preview_dets),
                    "confidences": [dd["confidence"] for dd in preview_dets],
                    "quality": "Single sampled frame; boxes from API vision, scores model-estimated and unvalidated."},
        "processing": {"framesProcessed": info["frames_sampled"], "framesTotal": info["frames_total"],
                       "sampling": info["sampling"],
                       "previewFrameIndex": mid["frame_idx"],
                       "previewNote": "The preview is one sampled frame, not evidence about the rest."},
        "reliability": {"detections": "needs_review", "movement": "needs_review", "tracking": "unavailable"},
        "counts": {"kind": "sampled frame-level API detections, not unique fish", "uniqueFish": None},
        "warnings": ["Individual fish tracking is not part of this analysis, so no tracking metrics are reported.",
                     api_note,
                     info["sampling"] + "."],
    }
    (d / "result.json").write_text(json.dumps(result), encoding="utf-8")
    job.update(state="completed", error=None)
    _write(d, job)
    history.record("video_analysis", job_id=job["id"], video_name=job["filename"],
                   backend="api", status="completed",
                   detections_mean=s["detections_mean"],
                   frames_sampled=info["frames_sampled"], frames_total=info["frames_total"])


def _split_reasons(reasons):
    movement = [r for r in reasons if r.startswith("camera drifted")]
    return [r for r in reasons if r not in movement], movement


def _run(d: Path):
    job = _read(d)
    job["state"] = "processing"
    _write(d, job)
    t0 = time.perf_counter()
    try:
        if vision_backend() == "api":
            _run_api(d, job, t0)
            return
        from ultralytics import YOLO
        import torch

        video = d / job["video"]
        df = sm.process(video)
        if df.empty:
            raise RuntimeError("No frames could be read from the video.")
        s = sm.summarize(df, df.attrs["expected_frames"])
        df.to_csv(d / "frames.csv", index=False)

        idx = len(df) // 2                                  # one representative frame: the middle of the video
        cap = cv2.VideoCapture(str(video))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, img = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError("Could not read the preview frame.")
        res = YOLO(str(sm.DETECTOR)).predict(img, conf=sm.CONF, imgsz=640, device=0 if torch.cuda.is_available() else "cpu", verbose=False)[0]
        cv2.imwrite(str(d / "original.jpg"), img)
        cv2.imwrite(str(d / "annotated.jpg"), res.plot())   # genuine model output (boxes, masks, scores)

        det_reasons, mov_reasons = _split_reasons(s["reliability_reasons"])
        base = f"/api/analyses/{job['id']}/frames"
        result = {
            "videoName": job["filename"], "fps": s["fps"], "frames": s["frames_read"],
            "processingSec": round(time.perf_counter() - t0, 2),
            "detections": {"meanPerFrame": s["detections_mean"], "min": s["detections_min"], "max": s["detections_max"],
                           "framesWithoutDetection": s["frames_without_detection"],
                           "reliable": not det_reasons, "reasons": det_reasons},
            "movement": {"reliable": not (det_reasons or mov_reasons), "meanMaskAreaFrac": s["mask_area_frac_mean"],
                         "cameraDriftDiagonals": s["camera_path_frac"], "reasons": det_reasons + mov_reasons},
            "preview": {"originalUrl": f"{base}/original", "annotatedUrl": f"{base}/annotated",
                        "timestampSec": float(df.time_sec.iloc[idx]), "detections": len(res.boxes),
                        "confidences": [round(float(c), 3) for c in res.boxes.conf.cpu().numpy()],   # model scores, not proof of correctness
                        "quality": "Single frame; segmentation quality not validated for this video"},
            "processing": {"framesProcessed": s["frames_read"], "framesTotal": s["frames_expected"], "sampling": "every frame, no sampling",
                           "previewFrameIndex": idx, "previewNote": "The preview is one frame (the middle of the video), not evidence about the rest."},
            # "reliable" is reserved for a metric validated on this camera/tank; none is, so a passed screen is only "needs_review".
            "reliability": {"detections": "unreliable" if det_reasons else "needs_review",
                            "movement": "unreliable" if (det_reasons or mov_reasons) else "needs_review", "tracking": "unavailable"},
            "counts": {"kind": "frame-level detections, not unique fish", "uniqueFish": None},
            "warnings": ["Individual fish tracking is not part of this analysis, so no tracking metrics are reported.",
                         "School-level metrics describe detected regions, not validated fish speed."],
        }
        (d / "result.json").write_text(json.dumps(result), encoding="utf-8")
        job.update(state="completed", error=None)
        history.record("video_analysis", job_id=job["id"], video_name=job["filename"],
                       backend="yolo", status="completed",
                       detections_mean=s["detections_mean"],
                       frames_processed=s["frames_read"], frames_total=s["frames_expected"])
    except Exception as e:  # report a concise, path-free message
        msg = re.sub(r"[A-Za-z]:[\\/][^\s'\"]*", "<path>", f"{type(e).__name__}: {e}")
        job.update(state="failed", error=msg[:300])
        history.record("video_analysis", job_id=job["id"], video_name=job.get("filename"),
                       backend=vision_backend(), status="failed", error=msg[:300])
    _write(d, job)


def _video_result(job_id):
    """(result, reason) for the combined assessment; only a completed job has results."""
    d = _dir(job_id)
    if d is None:
        return None, "Unknown video job."
    j = _read(d)
    if j["state"] != "completed":
        return None, f"Video analysis is {j['state']}."
    return json.loads((d / "result.json").read_text(encoding="utf-8")), None


def _fail_interrupted():
    """Jobs left queued/processing by a previous server run can never finish: mark them failed."""
    if JOBS.is_dir():
        for d in JOBS.iterdir():
            if (d / "job.json").is_file():
                j = _read(d)
                if j["state"] in ("queued", "processing"):
                    j.update(state="failed", error="Interrupted by a server restart.")
                    _write(d, j)


JOBS.mkdir(parents=True, exist_ok=True)
water.init(JOBS.parent, _video_result)
_fail_interrupted()


# ---------------------------------------------------------------- farmer alerts + dashboard (B/E)
def _false_flags(rows):
    ids = alert_engine.false_alarm_ids()
    return [{**r, "false_alarm": r.get("id") in ids} for r in rows]


async def alerts_list(request):
    try:
        limit = int(request.query_params.get("limit") or 50)
    except ValueError:
        limit = 50
    return JSONResponse({"alerts": _false_flags(alert_engine.recent(limit)),
                         "config": alert_engine.config_summary(),
                         "khatra": alert_engine.khatra(),
                         "note": ("Alerts are advisory only. RAS main pump must stay 24x7; "
                                  "no command is ever sent to hardware.")})


async def alerts_test(_):
    return JSONResponse(alert_engine.test_alert())


async def auth_status(_):
    # Additive field for the UI rollback switch: the frontend reads auth_mode
    # from this PUBLIC endpoint so AQUA_AUTH_MODE=open also removes the login
    # screen, not just the server-side middleware gate. Existing keys unchanged.
    body = auth_engine.status()
    body["auth_mode"] = os.environ.get("AQUA_AUTH_MODE", "full").strip().lower() or "full"
    return JSONResponse(body)


async def auth_request_otp(request):
    try:
        payload = await request.json()
    except Exception:
        return _err(400, 'Send JSON: {"phone": "+91..."}.')
    res = await run_in_threadpool(auth_engine.request_otp, str(payload.get("phone") or ""))
    return JSONResponse(res)


async def auth_verify_otp(request):
    try:
        payload = await request.json()
    except Exception:
        return _err(400, 'Send JSON: {"phone": "+91...", "code": "123456"}.')
    res = await run_in_threadpool(auth_engine.verify_otp, str(payload.get("phone") or ""),
                                  str(payload.get("code") or ""))
    return JSONResponse(res)


async def alerts_false_alarm(request):
    try:
        payload = await request.json()
    except Exception:
        return _err(400, 'Send JSON: {"id": "<alert id>"}.')
    rec = alert_engine.mark_false_alarm(str(payload.get("id") or ""), payload.get("note"))
    if rec is None:
        return _err(404, "Unknown alert id.")
    return JSONResponse({"marked": True, "false_alarm": rec})


async def alerts_settings_get(_):
    return JSONResponse(alert_engine.get_alert_settings())


async def alerts_settings_put(request):
    try:
        payload = await request.json()
    except Exception:
        return _err(400, 'Send JSON: {"cooldown_min": {"R2": 90, ...}}.')
    updates = payload.get("cooldown_min") if isinstance(payload, dict) else None
    if not isinstance(updates, dict):
        return _err(400, 'Expected {"cooldown_min": {"R2": 90, ...}}.')
    return JSONResponse(alert_engine.set_alert_settings(updates))


def _motor_advice(risk):
    level = risk.get("level")
    text = {
        "HIGH": "Dawn oxygen risk is HIGH (estimate). Keep aeration running overnight and check the water between 04:00 and 06:00.",
        "MEDIUM": "Oxygen risk is MEDIUM (estimate). Review the aeration schedule and check the water in the morning.",
        "LOW": "Oxygen risk is LOW (estimate). Keep the normal aeration schedule.",
        "INSUFFICIENT_DATA": "Not enough sensor data for an estimate; watch the weather and surface fish activity.",
    }.get(level, "Check the sensor data.")
    return {"level": level, "score": risk.get("score"), "text": text,
            "pump_rule": "RAS main pump must run 24x7 - never switch it off.",
            "provisional": True, "advisory_only": True}


async def dashboard(_):
    rules = alert_engine.current_rules()
    risk = predict_engine.dawn_risk()
    behavior = behavior_engine.current_anomaly()
    sms = alert_engine.config_summary()
    recent = _false_flags(alert_engine.recent(5))
    return JSONResponse({
        "khatra": alert_engine.khatra(rules),
        "motor": _motor_advice(risk),
        "energy": {"value": "--", "unit": "",
                   "note": "An energy-saving estimate needs a dissolved-oxygen sensor; no measurement is available yet."},
        "sms": {**sms, "last_alert": recent[0] if recent else None},
        "alerts": recent,
        "sensors": {"latest": sensor_feed.latest(), "stats": sensor_feed.stats()},
        "prediction": {"dawn_risk": risk, "behavior_anomaly": behavior},
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "disclaimer": ("PROVISIONAL/EXPERIMENTAL. Advisory only; no pump/feeder/relay control. "
                       "RAS main pump 24x7. Turbidity is raw ADC, not NTU."),
    })


async def predictions(_):
    if sensor_feed.configured():
        try:
            await run_in_threadpool(sensor_feed.poll_once)
        except Exception:
            pass
    return JSONResponse(predict_engine.summary())


async def behavior_stats_route(_):
    return JSONResponse(behavior_engine.summary())


async def sensors_status(_):
    return JSONResponse(sensor_feed.status())


@asynccontextmanager
async def _lifespan(_app):
    """Background pollers (read-only sensors, alert rules, weekly digest)."""
    if os.environ.get("AQUA_SCHEDULER", "1").strip().lower() not in ("0", "false", "no", "off", ""):
        try:
            from backend.app.services import backup_service
            backup_service.maybe_backup()
        except Exception:
            pass
        try:
            sensor_feed.start()
            alert_engine.start()
        except Exception:
            pass
    try:
        yield
    finally:
        try:
            alert_engine.stop()
            sensor_feed.stop()
        except Exception:
            pass


from backend.app.auth.routes import ROUTES as AUTH_ROUTES
from backend.app.routes.do_routes import ROUTES as DO_ROUTES
from backend.app.routes.behaviour_routes import ROUTES as BEHAVIOUR_ROUTES
from backend.app.routes.feeding_routes import ROUTES as FEEDING_ROUTES
from backend.app.routes.system_routes import ROUTES as SYSTEM_ROUTES
from backend.app.middleware.auth_middleware import AuthMiddleware

app = Starlette(
    routes=[
        Route("/health", health),
        *AUTH_ROUTES,
        Route("/api/videos", upload, methods=["POST"]),
        Route("/api/analyses", start, methods=["POST"]),
        Route("/api/analyses/{job_id}", status),
        Route("/api/analyses/{job_id}/results", results),
        Route("/api/analyses/{job_id}/frames/{kind}", frame),
        Route("/api/live/detect", live_detect, methods=["POST"]),
        Route("/api/live/track", live_track, methods=["POST"]),
        Route("/api/llm-status", llm_status),
        Route("/api/vision-status", vision_status),
        Route("/api/tracks", list_tracks),
        Route("/api/behavior", behavior, methods=["POST"]),
        Route("/api/risk", risk, methods=["POST"]),
        Route("/api/explanation", explanation, methods=["POST"]),
        Route("/api/history", history_list),
        Route("/api/advice", advice, methods=["POST"]),
        Route("/api/auth/status", auth_status),
        Route("/api/auth/request-otp", auth_request_otp, methods=["POST"]),
        Route("/api/auth/verify-otp", auth_verify_otp, methods=["POST"]),
        Route("/api/alerts", alerts_list),
        Route("/api/alerts/test", alerts_test, methods=["POST"]),
        Route("/api/alerts/false-alarm", alerts_false_alarm, methods=["POST"]),
        Route("/api/alerts/settings", alerts_settings_get, methods=["GET"]),
        Route("/api/alerts/settings", alerts_settings_put, methods=["PUT"]),
        Route("/api/dashboard", dashboard),
        Route("/api/predictions", predictions),
        Route("/api/behavior-stats", behavior_stats_route),
        Route("/api/sensors", sensors_status),
        *water.ROUTES,
        *DO_ROUTES,
        *BEHAVIOUR_ROUTES,
        *FEEDING_ROUTES,
        *SYSTEM_ROUTES,
    ],
    middleware=[
        Middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["*"], allow_credentials=True),
        Middleware(AuthMiddleware),
    ],
    lifespan=_lifespan,
)


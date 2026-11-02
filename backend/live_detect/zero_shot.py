"""Zero-shot live engines (Phase 2): YOLOWorld, Florence-2, optional Ollama, FastSAM masks.

Every adapter takes one BGR frame (np.ndarray) and returns a list of dicts:

    {"box": [x1, y1, x2, y2],   # normalised 0-1, same contract as predict_tiled
     "confidence": float,
     "outline": None | [[x, y], ...]}

so the rest of the live path (sanitizer, tracker, UI) stays untouched.
The live_detect package is otherwise CPU-only and offline; this module is the
exception: world/florence/fastsam weights are fetched lazily on first use
(ultralytics release assets / Hugging Face) and cached, and weights are cached
by ultralytics in the working directory.

Engines are selected by backend.main._live_predict from
AQUA_LIVE_ENGINE=friend|world|florence (default friend = the existing path).
An engine that cannot run here (no Ollama, no free VRAM, no weights and no
network) raises EngineUnavailable instead of silently degrading.
"""
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import urllib.request

import cv2

log = logging.getLogger("aqua.live_detect")

WORLD_WEIGHTS = os.environ.get("AQUA_WORLD_WEIGHTS", "yolov8s-worldv2.pt")  # size s only (6 GB GPU)
WORLD_CLASSES = ("fish", "tilapia", "school of fish")
# microsoft/Florence-2-base ships custom code + no image-token config, so the
# transformers-5 native API cannot load it (proven: RobertaTokenizer has no
# attribute image_token). florence-community/Florence-2-base is HF's conversion
# of the same weights for the native API (<image> token id 51289, loc tokens).
FLORENCE_ID = os.environ.get("AQUA_FLORENCE_MODEL", "florence-community/Florence-2-base")
FASTSAM_WEIGHTS = os.environ.get("AQUA_FASTSAM_WEIGHTS", "FastSAM-s.pt")
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_VRAM_MIN = 3.5 * 1024 ** 3  # per spec: >= 3.5 GB free after loading the world model
# Florence-2 <OD> emits no per-box scores. Contract requires a float, so every
# box carries this placeholder; the eval tables mark Florence conf as N/A-meaningful.
FLORENCE_CONF = 0.5


class EngineUnavailable(RuntimeError):
    """The engine cannot run on this machine (missing runtime/weights/VRAM)."""


_lock = threading.RLock()
_world = None
_florence = None
_fastsam = None


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _want_masks():
    raw = os.environ.get("AQUA_WANT_MASKS")
    if raw is None:
        return False
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _device():
    import torch
    return 0 if torch.cuda.is_available() else "cpu"


def _box_iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    bb = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = aa + bb - inter
    return inter / union if union > 0 else 0.0


def _thin(points, limit=80):
    step = max(1, -(-len(points) // limit))   # ceiling, so at most `limit` points
    return [[round(x, 4), round(y, 4)] for x, y in points[::step]]


# ------------------------------------------------------------------ YOLOWorld
def load_world():
    """Lazy singleton; raises EngineUnavailable when weights cannot be loaded
    (download needs network on first use; the file is cached afterwards)."""
    global _world
    from ultralytics import YOLOWorld
    with _lock:
        if _world is None:
            try:
                model = YOLOWorld(WORLD_WEIGHTS)
                model.set_classes(list(WORLD_CLASSES))
            except Exception as e:
                raise EngineUnavailable(f"YOLOWorld weights unavailable ({WORLD_WEIGHTS}): {e}") from e
            _world = model
            log.info("zero_shot: world loaded classes=%s", ",".join(WORLD_CLASSES))
    return _world


def detect_world(img, conf=None):
    """Open-vocabulary fish detection (yolov8s-worldv2, size s only)."""
    model = load_world()
    if conf is None:
        conf = _env_float("AQUA_WORLD_CONF", 0.25)
    with _lock:
        res = model.predict(img, conf=conf, imgsz=640, device=_device(), verbose=False)[0]
    dets = []
    for i in range(len(res.boxes)):
        x1, y1, x2, y2 = (max(0.0, min(1.0, float(v))) for v in res.boxes.xyxyn[i])
        dets.append({"box": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                     "confidence": round(float(res.boxes.conf[i]), 3),
                     "outline": None})
    if dets and _want_masks():
        _attach_fastsam(img, dets)
    return dets


# ------------------------------------------------------------------ Florence-2
_LOC_RUN = re.compile(r"([^<]+)((?:<loc_\d+>){4,})")


def _parse_loc_boxes(text):
    """Parse Florence-2 '<label><loc_x><loc_y><loc_x><loc_y>...' answers into
    (label, normalised box) pairs. 1000 bins, floor mode: (bin + 0.5) / 1000.
    (The native post_process_generation of transformers 5.20 crashes on
    description_with_bboxes, so the format is parsed here.)"""
    out = []
    for m in _LOC_RUN.finditer(text):
        label = m.group(1).strip().lower()
        locs = [int(v) for v in re.findall(r"<loc_(\d+)>", m.group(2))]
        for i in range(0, len(locs) - 3, 4):
            x1, y1, x2, y2 = ((v + 0.5) / 1000.0 for v in locs[i:i + 4])
            x1, x2 = sorted((max(0.0, min(1.0, x1)), max(0.0, min(1.0, x2))))
            y1, y2 = sorted((max(0.0, min(1.0, y1)), max(0.0, min(1.0, y2))))
            out.append((label, [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]))
    return out


def load_florence():
    """Lazy singleton (processor, model, device); fp16 on CUDA, fp32 on CPU."""
    global _florence
    from transformers import AutoProcessor, Florence2ForConditionalGeneration
    import torch
    with _lock:
        if _florence is None:
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if dev == "cuda" else torch.float32
            try:
                processor = AutoProcessor.from_pretrained(FLORENCE_ID)
                model = Florence2ForConditionalGeneration.from_pretrained(FLORENCE_ID, dtype=dtype)
            except Exception as e:
                raise EngineUnavailable(f"Florence-2 unavailable ({FLORENCE_ID}): {e}") from e
            model.to(dev)
            model.eval()
            _florence = (processor, model, dev)
            log.info("zero_shot: florence loaded device=%s dtype=%s", dev, dtype)
    return _florence


def _label_ok(label):
    """AQUA_FLORENCE_LABELS (comma list, default 'fish') filters OD labels; empty = keep all."""
    allow = os.environ.get("AQUA_FLORENCE_LABELS", "fish").strip().lower()
    terms = [t.strip() for t in allow.split(",") if t.strip()]
    if not terms:
        return True
    return any(t in str(label).lower() for t in terms)


def detect_florence(img):
    """Florence-2 caption-to-detection. AQUA_FLORENCE_TASK overrides the task:
    '<OD>' (default) or '<OPEN_VOCABULARY_DETECTION>fish' style prompts."""
    import torch
    from PIL import Image
    task = os.environ.get("AQUA_FLORENCE_TASK", "<OD>").strip() or "<OD>"
    processor, model, dev = load_florence()
    image = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    inputs = processor(text=task, images=image, return_tensors="pt")
    feeds = {k: v.to(dev) for k, v in inputs.items() if k != "pixel_values"}
    feeds["pixel_values"] = inputs["pixel_values"].to(dev, dtype=model.dtype)
    with _lock:
        with torch.inference_mode():
            ids = model.generate(**feeds, max_new_tokens=1024, num_beams=3, do_sample=False)
    text = processor.batch_decode(ids, skip_special_tokens=False)[0]
    dets = []
    for label, box in _parse_loc_boxes(text):
        if not _label_ok(label):
            continue
        dets.append({"box": box, "confidence": FLORENCE_CONF, "outline": None})
    if dets and _want_masks():
        _attach_fastsam(img, dets)
    return dets


# ------------------------------------------------------------------ Ollama VLM
def detect_ollama(img):
    """Local VLM path (qwen2.5vl via Ollama). Guarded per spec: the CLI must
    exist, `ollama list` must carry a qwen2.5vl tag, and >= 3.5 GB VRAM must be
    free after the world model is loaded. On this laptop the first guard raises
    EngineUnavailable (Ollama is not installed)."""
    exe = shutil.which("ollama")
    if not exe:
        raise EngineUnavailable("Ollama is not installed (no `ollama` on PATH).")
    try:
        listed = subprocess.run([exe, "list"], capture_output=True, text=True, timeout=20)
    except Exception as e:
        raise EngineUnavailable(f"`ollama list` failed: {e}") from e
    tags = f"{listed.stdout or ''}\n{listed.stderr or ''}".lower()
    wanted = os.environ.get("AQUA_OLLAMA_MODEL", "qwen2.5vl").strip().lower()
    tag = next((line.split()[0] for line in tags.splitlines() if wanted in line), None)
    if not tag:
        raise EngineUnavailable(f"'{wanted}' not found in `ollama list`.")
    try:
        load_world()   # spec: the VRAM check runs after the world model is resident
    except EngineUnavailable:
        pass
    import torch
    if not torch.cuda.is_available():
        raise EngineUnavailable("Ollama engine needs a CUDA device for the VRAM check.")
    free, _total = torch.cuda.mem_get_info()
    if free < OLLAMA_VRAM_MIN:
        raise EngineUnavailable(f"free VRAM {free / 1024 ** 3:.1f} GB < 3.5 GB after loading the world model.")
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return []
    prompt = ("Detect every fish in this frame. Reply ONLY with JSON: "
              '{"boxes": [[x1, y1, x2, y2, confidence], ...]} with coordinates '
              "normalised 0-1 (x=width, y=height). Empty list when no fish.")
    payload = json.dumps({"model": wanted, "prompt": prompt,
                          "images": [base64.b64encode(buf.tobytes()).decode()],
                          "stream": False, "format": "json"}).encode()
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        raise EngineUnavailable(f"Ollama request failed: {e}") from e
    try:
        data = json.loads(body.get("response") or "{}")
    except (TypeError, ValueError):
        return []
    dets = []
    for b in data.get("boxes") or []:
        try:
            x1, y1, x2, y2 = (float(v) for v in b[:4])
            conf = float(b[4]) if len(b) > 4 else 0.5
        except (TypeError, ValueError):
            continue
        x1, y1 = max(0.0, min(1.0, x1)), max(0.0, min(1.0, y1))
        x2, y2 = max(0.0, min(1.0, x2)), max(0.0, min(1.0, y2))
        dets.append({"box": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                     "confidence": round(min(1.0, max(0.0, conf)), 3), "outline": None})
    if dets and _want_masks():
        _attach_fastsam(img, dets)
    return dets


# ------------------------------------------------------------------ FastSAM masks
def load_fastsam():
    global _fastsam
    from ultralytics import FastSAM
    with _lock:
        if _fastsam is None:
            try:
                _fastsam = FastSAM(FASTSAM_WEIGHTS)
            except Exception as e:
                raise EngineUnavailable(f"FastSAM weights unavailable ({FASTSAM_WEIGHTS}): {e}") from e
    return _fastsam


def _attach_fastsam(img, dets):
    """AQUA_WANT_MASKS=1: attach the best-IoU FastSAM segment outline per box."""
    model = load_fastsam()
    with _lock:
        res = model.predict(img, imgsz=640, device=_device(), verbose=False)[0]
    if res.masks is None or res.boxes is None or len(res.boxes) == 0:
        return dets
    seg_boxes = res.boxes.xyxyn.tolist()
    polys = res.masks.xyn
    for d in dets:
        best, best_iou = None, 0.0
        for i, sb in enumerate(seg_boxes):
            iou = _box_iou(d["box"], sb)
            if iou > best_iou:
                best, best_iou = i, iou
        if best is not None and best_iou > 0:
            poly = polys[best].tolist()
            if len(poly) > 2:
                d["outline"] = _thin(poly)
    return dets

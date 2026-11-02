"""Adaptive live detection: single pass first, tiled escalation only when weak.

Why: a 640-trained detector sees close-up phone-frame fish at a scale it never
learned. Instead of always paying for tiles (CPU!), run one normal pass and
escalate to overlapping tiles + NMS merge only when the best confidence is
below `trigger` (or nothing was found).

Each det: dict(box=[x1,y1,x2,y2] 0-1, conf, area_frac, source, edges).
`source` is 'single' | 'tile'; `edges` is Canny edge density inside the box.
`adaptive_sanitize()` keeps large boxes only when edge-rich (textured fish),
so a real close-up fish survives while a flat tank/water slab is rejected.
"""
import logging
import time

import cv2
import numpy as np

log = logging.getLogger("aqua.live_detect")

TILE_GRID = 2          # 2x2 overlapping tiles on escalation
TILE_OVERLAP = 0.25    # tile overlap fraction (each tile covers 62.5% per side)
NMS_IOU = 0.50         # merge threshold across single + tile detections


def edge_density(gray, box):
    """Canny edge-pixel fraction inside box (0-1 coords). Flat slabs ~0.005,
    textured fish an order of magnitude higher (measured, see tests)."""
    h, w = gray.shape[:2]
    x1, y1, x2, y2 = (int(v * s) for v, s in zip(box, (w, h, w, h)))
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return 0.0
    crop = gray[y1:y2, x1:x2]
    edges = cv2.Canny(crop, 50, 150)
    return float((edges > 0).mean())


def adaptive_sanitize(box, gray, edge_min):
    """True = keep: region is edge-rich (textured). False = flat slab, drop
    (caller must record the decision with a reason, never silently)."""
    return edge_density(gray, box) >= edge_min


def _thin_pts(points, limit=80):
    step = max(1, -(-len(points) // limit))   # ceiling, at most `limit` points
    return [[round(x, 4), round(y, 4)] for x, y in points[::step]]


def _infer(model, img, conf, imgsz, device, source):
    res = model.predict(img, conf=conf, imgsz=imgsz, device=device,
                        verbose=False)[0]
    h, w = img.shape[:2]
    dets = []
    n = len(res.boxes)
    gray = None
    has_masks = res.masks is not None and len(res.masks.xyn) == n
    for i in range(n):
        x1, y1, x2, y2 = res.boxes.xyxyn[i].tolist()
        box = [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]
        if gray is None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        d = {
            "box": box,
            "conf": round(float(res.boxes.conf[i]), 3),
            "area_frac": round((x2 - x1) * (y2 - y1), 4),
            "source": source,
            "edges": round(edge_density(gray, box), 4),
        }
        if has_masks:
            d["outline"] = _thin_pts(res.masks.xyn[i].tolist())
        dets.append(d)
    return dets


def _to_global(tile_box, tx, ty, tw, th):
    """Tile-local 0-1 box -> frame-global 0-1 box."""
    x1, y1, x2, y2 = tile_box
    return [round(tx + x1 * tw, 4), round(ty + y1 * th, 4),
            round(tx + x2 * tw, 4), round(ty + y2 * th, 4)]


def _nms(dets, iou_thr=NMS_IOU):
    """Highest-confidence-first box NMS over normalised boxes."""
    kept = []
    for d in sorted(dets, key=lambda d: -d["conf"]):
        keep = True
        for k in kept:
            a, b = d["box"], k["box"]
            ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
            ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            aa = (a[2] - a[0]) * (a[3] - a[1])
            bb = (b[2] - b[0]) * (b[3] - b[1])
            union = aa + bb - inter
            if union > 0 and inter / union >= iou_thr:
                keep = False
                break
        if keep:
            kept.append(d)
    return kept


def _tiles(frame):
    """Yield (tile_img, tx, ty, tw, th) for a 2x2 overlapping grid."""
    h, w = frame.shape[:2]
    span = (1.0 + TILE_OVERLAP) / TILE_GRID  # 0.625 per side
    step = 1.0 / TILE_GRID                    # 0.5 offset
    for gy in range(TILE_GRID):
        for gx in range(TILE_GRID):
            tx, ty = gx * step, gy * step
            x1, y1 = int(tx * w), int(ty * h)
            x2, y2 = int(min(1.0, tx + span) * w), int(min(1.0, ty + span) * h)
            yield frame[y1:y2, x1:x2], tx, ty, (x2 - x1) / w, (y2 - y1) / h


def detect_adaptive(model, frame_bgr, conf=0.20, trigger=0.25, imgsz=640,
                    mode="auto", sanitize=True, device="cpu"):
    """Adaptive detection on one BGR frame. Returns list of det dicts.

    mode="auto": single pass; escalate to tiles only when weak
    (no detections or best conf < trigger). mode="single": never tile.
    `sanitize` is kept for signature compatibility; geometric + adaptive
    filtering lives in backend.main._sanitize_live_detections (which reads
    the `edges` value produced here). Latency is logged at INFO.
    """
    import torch
    if device == "auto":
        device = 0 if torch.cuda.is_available() else "cpu"
    t0 = time.perf_counter()
    dets = _infer(model, frame_bgr, conf, imgsz, device, "single")
    best = max((d["conf"] for d in dets), default=0.0)
    escalated = False
    if mode == "auto" and (not dets or best < trigger):
        escalated = True
        for tile, tx, ty, tw, th in _tiles(frame_bgr):
            for d in _infer(model, tile, conf, imgsz, device, "tile"):
                d["box"] = _to_global(d["box"], tx, ty, tw, th)
                if "outline" in d:
                    d["outline"] = [[round(tx + lx * tw, 4), round(ty + ly * th, 4)]
                                    for lx, ly in d["outline"]]
                x1, y1, x2, y2 = d["box"]
                d["area_frac"] = round((x2 - x1) * (y2 - y1), 4)
                dets.append(d)
        dets = _nms(dets)
    ms = round((time.perf_counter() - t0) * 1000)
    log.info("detect_adaptive: n=%d best=%.2f escalated=%s ms=%d",
             len(dets), max((d["conf"] for d in dets), default=0.0),
             escalated, ms)
    return dets

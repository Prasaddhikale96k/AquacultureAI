"""Sampled video analysis with API vision models (replaces the YOLO pipeline).

The YOLO pipeline runs locally on EVERY frame with pixel masks. API vision
models cannot do that (seconds per call, no masks, rate limits), so this module
samples frames (default 1 fps, max 30 frames per video) and calls
backend.vision.detect_image once per sampled frame.

Output is deliberately coarser than the YOLO pipeline and is labeled as such:
- frame-level detection COUNTS only (no unique-fish count, no tracking);
- box-area fractions as a coarse presence proxy (NOT mask area, NOT speed);
- no camera-motion estimation (API mode cannot separate camera from fish motion);
- reliability is always needs_review/unavailable: API output is zero-shot and
  unvalidated for the user's tank, lighting and camera.
"""
import os
from pathlib import Path

import cv2

from backend import vision

try:
    TARGET_FPS = max(0.1, float(os.environ.get("API_VISION_FPS", "1")))
except ValueError:
    TARGET_FPS = 1.0
try:
    MAX_FRAMES = max(1, int(os.environ.get("API_VISION_MAX_FRAMES", "30")))
except ValueError:
    MAX_FRAMES = 30


def analyze(video_path):
    """Sample frames and detect fish in each. Returns (rows, preview_bgr, preview_dets, info).

    rows: [{frame_idx, time_sec, detections, mean_confidence, mean_box_area_frac, provider, model}]
    info: {fps, frames_total, frames_sampled, sampling, providers, fallback_used, tried}
    """
    video_path = Path(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError("The video could not be decoded.")
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not video_fps or video_fps <= 0:
        cap.release()
        raise RuntimeError("The video's frame rate is unavailable.")
    step = max(1, round(video_fps / TARGET_FPS))

    idxs = list(range(0, total if total > 0 else 0, step))[:MAX_FRAMES]
    if not idxs:  # very short / unknown length: grab what we can sequentially
        idxs = list(range(MAX_FRAMES))
    rows, providers, tried_all, fallback = [], [], [], False
    preview_bgr, preview_dets = None, []
    for n, fi in enumerate(idxs):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, img = cap.read()
        if not ok or img is None:
            if n == 0:
                cap.release()
                raise RuntimeError("No frames could be read from the video.")
            break
        out = vision.detect_image(img)
        dets = out["detections"]
        area = sum((d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1]) for d in dets)
        confs = [d["confidence"] for d in dets]
        rows.append({
            "frame_idx": fi,
            "time_sec": round(fi / video_fps, 3),
            "detections": len(dets),
            "mean_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
            "mean_box_area_frac": round(area, 4),
            "provider": out["provider"],
            "model": out["model"],
        })
        providers.append(f"{out['provider']}:{out['model']}")
        tried_all.extend(t for t in out["tried"] if t not in tried_all)
        fallback = fallback or out["fallback_used"]
        if n == len(idxs) // 2:
            preview_bgr, preview_dets = img, dets
    cap.release()
    if not rows:
        raise RuntimeError("No frames could be read from the video.")
    if preview_bgr is None:
        raise RuntimeError("No frames could be read from the video.")
    info = {
        "fps": round(video_fps, 3),
        "frames_total": total,
        "frames_sampled": len(rows),
        "sampling": (f"sampled frames at ~{TARGET_FPS:g} fps ({len(rows)} of {total} frames) "
                     f"through API vision models; events between samples are missed"),
        "providers": sorted(set(providers)),
        "fallback_used": fallback,
        "tried": tried_all,
    }
    return rows, preview_bgr, preview_dets, info


def summarize(rows):
    """Aggregate sampled counts into a screening summary (screening only)."""
    counts = [r["detections"] for r in rows]
    areas = [r["mean_box_area_frac"] for r in rows]
    n = len(rows)
    changes = sum(1 for a, b in zip(counts, counts[1:]) if a != b)
    return {
        "detections_mean": round(sum(counts) / n, 2),
        "detections_min": min(counts),
        "detections_max": max(counts),
        "frames_without_detection": sum(1 for c in counts if c == 0),
        "box_area_frac_mean": round(sum(areas) / n, 4),
        "count_change_rate": round(changes / max(1, n - 1), 3),
    }

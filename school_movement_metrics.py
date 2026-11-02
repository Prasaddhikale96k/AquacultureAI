"""School-level movement metrics for a recorded tank video (no individual fish identities needed).

Per frame: detection count, union mask area as a fraction of the frame, change in that area,
estimated global (camera) shift, and a camera-compensated motion energy.
Timestamps use the video's real FPS (an invalid FPS raises; it is never guessed).

Usage: python school_movement_metrics.py --video test_videos/tilapia_clear.mp4
Writes school_movement_<video stem>.csv next to this script.
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DETECTOR = ROOT / "runs/segment/runs/aquaculture/tilapia_seg/weights/best.pt"
CONF = 0.35                 # same detection threshold as the legacy analysis scripts
SMALL_WIDTH = 320           # frames are downscaled to this width for camera-shift and motion estimates
CAM_SHIFT_MAX_FRAC = 0.003  # frame-to-frame global shift above this fraction of the frame diagonal => camera moving
CAM_RESPONSE_MIN = 0.05     # phase-correlation response below this => shift estimate unreliable
# Plausibility limits from the project's own annotations (dataset/tilapia_yolo, measured Oct 2026:
# train 7,669 boxes max single-fish area 0.51 p99 0.287; test 6,604 boxes max 0.275; max 11 fish/file):
# the union of annotated fish covers at most 61% of a frame and has at most 11 fish.
# Single boxes above 0.40 (train p99.9) or spanning ~edge-to-edge are tank bands, not fish.
ANNOT_AREA_MAX = 0.55
ANNOT_DET_MAX = 11
SINGLE_BOX_MAX_FRAC = 0.40
FULL_SPAN_FRAC = 0.98


def plausible_box(box):
    """True only for fish-plausible boxes: area within annotated range and not a full-span tank band."""
    try:
        x1, y1, x2, y2 = (float(v) for v in box)
    except (TypeError, ValueError):
        return False
    area = (x2 - x1) * (y2 - y1)
    if area <= 0 or area > SINGLE_BOX_MAX_FRAC:
        return False
    if (x2 - x1) >= FULL_SPAN_FRAC or (y2 - y1) >= FULL_SPAN_FRAC:
        return False
    return True


def validated_fps(fps):
    if fps is None or not np.isfinite(fps) or fps <= 0:
        raise RuntimeError("Video FPS is unavailable or invalid; refusing to guess it.")
    return float(fps)


def union_mask_fraction(polygons, shape):
    """Fraction of the frame covered by the union of polygons (overlaps counted once); also returns the mask."""
    mask = np.zeros(shape[:2], np.uint8)
    for poly in polygons:
        if len(poly) >= 3:
            cv2.fillPoly(mask, [np.round(poly).astype(np.int32)], 1)
    return float(mask.sum()) / mask.size, mask


def small_gray(frame):
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    scale = SMALL_WIDTH / g.shape[1]
    return cv2.resize(g, (SMALL_WIDTH, max(1, round(g.shape[0] * scale))), interpolation=cv2.INTER_AREA)


def camera_shift(prev_gray, gray):
    """Global translation (dx, dy) of gray vs prev_gray in small-image pixels, and its response."""
    win = cv2.createHanningWindow(gray.shape[::-1], cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(prev_gray.astype(np.float32), gray.astype(np.float32), win)
    return dx, dy, response


def motion_energy(prev_gray, gray, dx, dy, region_small):
    """Mean |intensity change| (0-1) inside the fish region after undoing the estimated global shift."""
    h, w = gray.shape
    warped = cv2.warpAffine(prev_gray, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h), borderMode=cv2.BORDER_REPLICATE)
    region = region_small > 0
    if not region.any():
        return np.nan
    return float(np.abs(gray.astype(np.float32) - warped.astype(np.float32))[region].mean() / 255.0)


def process(video, model_path=DETECTOR):
    from ultralytics import YOLO
    import torch

    video = Path(video)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video}")
    fps = validated_fps(cap.get(cv2.CAP_PROP_FPS))
    expected = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    model = YOLO(str(model_path))
    device = 0 if torch.cuda.is_available() else "cpu"

    rows, prev_gray, prev_mask_small, prev_area, prev_det = [], None, None, None, None
    frame_no = 0
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        res = model.predict(frame, conf=CONF, imgsz=640, device=device, verbose=False)[0]
        n_boxes = len(res.boxes)
        keep = [i for i in range(n_boxes)
                if plausible_box(res.boxes.xyxyn[i].tolist())] if n_boxes else []
        if res.masks is not None and len(res.masks.xy) == n_boxes:
            polys = [res.masks.xy[i] for i in keep]
        else:
            polys = res.masks.xy if res.masks is not None else []
        area, mask = union_mask_fraction(polys, frame.shape)
        det = len(polys)
        gray = small_gray(frame)
        mask_small = cv2.resize(mask, gray.shape[::-1], interpolation=cv2.INTER_NEAREST)
        row = {"frame": frame_no, "time_sec": frame_no / fps, "fps": fps, "detections": det, "mask_area_frac": area,
               "delta_mask_area_frac": np.nan, "camera_shift_frac": np.nan, "camera_response": np.nan,
               "camera_moving": np.nan, "motion_energy": np.nan}
        # area change is only meaningful when both frames have detections (a miss would look like a huge change)
        if prev_area is not None and det > 0 and prev_det > 0:
            row["delta_mask_area_frac"] = area - prev_area
        if prev_gray is not None:
            dx, dy, resp = camera_shift(prev_gray, gray)
            diag = float(np.hypot(*gray.shape))
            shift = float(np.hypot(dx, dy)) / diag
            moving = shift > CAM_SHIFT_MAX_FRAC or resp < CAM_RESPONSE_MIN
            row.update(camera_shift_frac=shift, camera_response=float(resp), camera_moving=bool(moving))
            if not moving and (det > 0 or prev_det > 0):
                row["motion_energy"] = motion_energy(prev_gray, gray, dx, dy,
                                                     np.maximum(mask_small, prev_mask_small))
        rows.append(row)
        prev_gray, prev_mask_small, prev_area, prev_det = gray, mask_small, area, det
        frame_no += 1
    df = pd.DataFrame(rows)
    df.attrs.update(fps=fps, expected_frames=expected, frame_size=(int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))))
    cap.release()
    return df


def summarize(df, expected_frames=None):
    """Metrics plus 'reliability_reasons': empty only if no check below fired (heuristic limits, see constants)."""
    cm = df["camera_moving"].dropna().astype(bool)
    implausible = float(((df.mask_area_frac > ANNOT_AREA_MAX) | (df.detections > ANNOT_DET_MAX)).mean())
    cam_path = float(df.camera_shift_frac.sum())
    no_det = float((df.detections == 0).mean())
    reasons = []
    if expected_frames is not None and len(df) != expected_frames:
        reasons.append(f"read {len(df)} of {expected_frames} frames")
    if implausible > 0.2:
        reasons.append(f"{implausible:.0%} of frames have mask area above {ANNOT_AREA_MAX:.0%} of the frame or more than {ANNOT_DET_MAX} detections (limits taken from the tilapia annotations)")
    if no_det > 0.2:
        reasons.append(f"{no_det:.0%} of frames have no detection")
    if cam_path > 0.1:
        reasons.append(f"camera drifted {cam_path:.2f} frame diagonals in total; only translation is compensated")
    return {
        "frames_read": len(df), "frames_expected": expected_frames, "fps": float(df.fps.iloc[0]),
        "camera_path_frac": cam_path, "frames_implausible_frac": implausible,
        "reliability_reasons": reasons,
        "detections_mean": df.detections.mean(), "detections_min": int(df.detections.min()),
        "detections_max": int(df.detections.max()), "frames_without_detection": int((df.detections == 0).sum()),
        "mask_area_frac_mean": df.mask_area_frac.mean(), "mask_area_frac_max": df.mask_area_frac.max(),
        "abs_delta_mask_area_frac_mean": df.delta_mask_area_frac.abs().mean(),
        "camera_moving_frames_frac": float(cm.mean()) if len(cm) else np.nan,
        "motion_energy_valid_frames": int(df.motion_energy.notna().sum()),
        "motion_energy_mean": df.motion_energy.mean(), "motion_energy_median": df.motion_energy.median(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    args = ap.parse_args()
    video = Path(args.video)
    video = video if video.is_absolute() else ROOT / video
    df = process(video)
    if df.empty:
        raise SystemExit("No frames could be read; nothing written.")
    out = ROOT / f"school_movement_{video.stem}.csv"
    df.to_csv(out, index=False)
    s = summarize(df, df.attrs["expected_frames"])
    print(f"Video {video.name}: frame size {df.attrs['frame_size']}")
    for k, v in s.items():
        print(f"  {k}: {v:.5g}" if isinstance(v, float) else f"  {k}: {v}")
    print("Saved:", out)


if __name__ == "__main__":
    main()

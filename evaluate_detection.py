"""Comparative fish-detection evaluation on INDEPENDENT labeled test data.

Compares, on the identical test images:
  Arm A (local baseline): the weights actually served by the backend
        (school_movement_metrics.DETECTOR, tilapia_seg best.pt) — inference only.
  Arm B (API vision): backend/vision.py (Groq vision -> Gemini vision) on a small
        capped subset (each image = 1 API call). Requires keys; else Blocked.

Ground truth: dataset/tilapia_yolo/{split}/labels/*.txt (YOLO-seg polygons,
single class tilapia). Polygons are converted to bounding boxes for box-level
scoring. Matching: greedy by confidence at IoU >= 0.5 (configurable).

Metrics (per arm): TP/FP/FN, precision, recall, F1, FP per image, miss rate,
images evaluated, image size. No training, no tuning, no pseudo-labels.

Usage:
  python evaluate_detection.py [--split test] [--max-images 150] [--iou 0.5]
      [--api-images 12] [--conf 0.35] [--out eval_detection.json]

Selection policy: adopt an arm for production only if it wins on this test set
AND meets operational needs (latency, cost, masks). A higher public benchmark
score alone is never sufficient.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

DATASET = ROOT / "dataset" / "tilapia_yolo"


def read_gt(label_path):
    """YOLO-seg polygon lines -> list of [x1,y1,x2,y2] normalized boxes."""
    boxes = []
    with open(label_path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 7:  # need class + >=3 points
                continue
            try:
                nums = [float(x) for x in parts[1:]]
            except ValueError:
                continue
            xs, ys = nums[0::2], nums[1::2]
            if not xs or not ys:
                continue
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            if x2 > x1 and y2 > y1:
                boxes.append([x1, y1, x2, y2])
    return boxes


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    aa = (a[2] - a[0]) * (a[3] - a[1])
    bb = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (aa + bb - inter)


def score(preds, gts, iou_thr):
    """preds: list per image of [(box, conf)]. gts: list per image of [box].
    Greedy matching by descending confidence. Returns dict of metrics."""
    tp = fp = fn = 0
    for pd, gt in zip(preds, gts):
        matched = [False] * len(gt)
        for box, _ in sorted(pd, key=lambda x: -x[1]):
            best, bi = iou_thr, -1
            for i, g in enumerate(gt):
                if matched[i]:
                    continue
                v = iou(box, g)
                if v >= best:
                    best, bi = v, i
            if bi >= 0:
                matched[bi] = True
                tp += 1
            else:
                fp += 1
        fn += sum(1 for m in matched if not m)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "images": len(gts), "gt_boxes": sum(len(g) for g in gts),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(prec, 4), "recall": round(rec, 4),
        "f1": round(2 * prec * rec / (prec + rec), 4) if (prec + rec) else 0.0,
        "fp_per_image": round(fp / len(gts), 3) if gts else 0.0,
        "miss_rate": round(fn / (tp + fn), 4) if (tp + fn) else 0.0,
    }


def local_arm(images, conf):
    import school_movement_metrics as sm
    from ultralytics import YOLO
    import torch
    import cv2
    model = YOLO(str(sm.DETECTOR))
    device = 0 if torch.cuda.is_available() else "cpu"
    preds = []
    t0 = time.perf_counter()
    for p in images:
        img = cv2.imread(str(p))
        res = model.predict(img, conf=conf, imgsz=640, device=device, verbose=False)[0]
        boxes = []
        for i in range(len(res.boxes)):
            x1, y1, x2, y2 = res.boxes.xyxyn[i].tolist()
            boxes.append(([x1, y1, x2, y2], float(res.boxes.conf[i])))
        preds.append(boxes)
    dt = time.perf_counter() - t0
    return preds, {"device": "cuda" if device == 0 else "cpu", "seconds_total": round(dt, 1),
                   "ms_per_image": round(dt / len(images) * 1000, 1) if images else 0}


def api_arm(images):
    from backend import vision
    import cv2
    preds, providers = [], []
    for p in images:
        img = cv2.imread(str(p))
        if img is None:
            preds.append([])
            continue
        out = vision.detect_image(img)
        preds.append([(d["box"], d["confidence"]) for d in out["detections"]])
        providers.append(f"{out['provider']}:{out['model']}")
    return preds, {"providers": sorted(set(providers))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--max-images", type=int, default=0, help="0 = whole split")
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--api-images", type=int, default=12, help="cap for the API arm (1 call/image)")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--out", default="eval_detection.json")
    a = ap.parse_args()

    imgdir, lbldir = DATASET / "images" / a.split, DATASET / "labels" / a.split
    if not imgdir.is_dir() or not lbldir.is_dir():
        print(f"BLOCKED: dataset split not found: {imgdir} / {lbldir}")
        return 2
    pairs = [(p, lbldir / (p.stem + ".txt")) for p in sorted(imgdir.glob("*.jpg"))]
    pairs = [(p, l) for p, l in pairs if l.is_file()]
    if a.max_images > 0:
        pairs = pairs[:a.max_images]
    if not pairs:
        print("BLOCKED: no image/label pairs in split.")
        return 2
    print(f"Evaluating {len(pairs)} images from split '{a.split}' at IoU>={a.iou}")

    gts = [read_gt(l) for _, l in pairs]
    result = {"split": a.split, "iou_thr": a.iou, "images": [p.name for p, _ in pairs],
              "gt_boxes_total": sum(len(g) for g in gts)}

    import school_movement_metrics as sm
    result["local_weights"] = str(sm.DETECTOR)
    preds, perf = local_arm([p for p, _ in pairs], a.conf)
    result["local"] = {**score(preds, gts, a.iou), **perf}

    if os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        sub = pairs[:a.api_images]
        sub_gts = gts[:a.api_images]
        try:
            preds, perf = api_arm([p for p, _ in sub])
            result["api"] = {**score(preds, sub_gts, a.iou), **perf,
                             "images_subset": [p.name for p, _ in sub]}
        except Exception as e:
            result["api"] = {"status": "BLOCKED", "reason": f"{type(e).__name__}: {e}"[:200]}
    else:
        result["api"] = {"status": "BLOCKED",
                         "reason": "No GROQ_API_KEY/GEMINI_API_KEY configured; set keys to run the API arm."}

    Path(a.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    loc = result["local"]
    print(f"LOCAL best.pt: P={loc['precision']} R={loc['recall']} F1={loc['f1']} "
          f"TP={loc['tp']} FP={loc['fp']} FN={loc['fn']} on {loc['images']} images "
          f"({loc['ms_per_image']} ms/img, {loc['device']})")
    api = result["api"]
    if api.get("status") == "BLOCKED":
        print(f"API arm: BLOCKED — {api['reason']}")
    else:
        print(f"API vision {api.get('providers')}: P={api['precision']} R={api['recall']} F1={api['f1']} "
              f"TP={api['tp']} FP={api['fp']} FN={api['fn']} on {api['images']} images")
    print(f"Saved: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

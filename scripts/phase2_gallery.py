"""Phase 2 A/B gallery: friend (best.pt) vs world (YOLOWorld) vs florence (Florence-2).

Runs the three live engines on a fixed 12-frame pool (5 owner captures at the
C0-upright rotation + frames from both test videos), draws the RAW engine boxes
(no sanitizer applied - the live path sanitizes, this gallery shows capability),
and writes eval_ab/<frame>__<engine>.jpg, per-engine contact sheets, index.html
and gallery_data.json. Run with the project venv:

    .venv\\Scripts\\python.exe scripts\\phase2_gallery.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from backend.live_detect import predict_tiled as pt
from backend.live_detect import zero_shot as zs

OUT = ROOT / "eval_ab"
OWNER_DIR = ROOT / "dataset" / "live_captures" / "2026-10-17"
OWNER_FRAMES = ["075703-284.jpg", "075734-247.jpg", "075812-230.jpg",
                "075843-395.jpg", "075915-228.jpg"]
VIDEOS = [("tilapia_clear.mp4", [0, 60, 120, 180]),   # seconds*dummy -> indices at 30fps
          ("fish_tank.mp4", [0, 90, 180])]
ROT = 90          # C0 rotation oracle: upright at frontend Rotate=90 (CW)
FRIEND_CONF = 0.35
ENGINES = ["friend", "world", "florence"]
COLORS = {"friend": (0, 200, 255), "world": (80, 220, 80), "florence": (255, 140, 80)}


def rot90_cw(img):
    return np.rot90(img, k=-1) if ROT == 90 else img


def build_pool():
    pool = []
    for fn in OWNER_FRAMES:
        img = cv2.imread(str(OWNER_DIR / fn))
        if img is None:
            raise SystemExit(f"missing frame {fn}")
        pool.append((f"cap_{fn[:6]}", rot90_cw(img)))
    for vname, idxs in VIDEOS:
        cap = cv2.VideoCapture(str(ROOT / "test_videos" / vname))
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, fr = cap.read()
            if ok:
                pool.append((f"{vname[:9]}_{idx:03d}", fr))
        cap.release()
    return pool


def load_friend():
    from ultralytics import YOLO
    from backend import main as api
    return YOLO(api.live_weights())


def run_engine(engine, model, img):
    t = time.perf_counter()
    if engine == "friend":
        import torch
        raw = pt.detect_adaptive(model, img, conf=FRIEND_CONF, trigger=0.25, imgsz=640,
                                 mode="auto", device=0 if torch.cuda.is_available() else "cpu")
        dets = [{"box": d["box"], "confidence": d["conf"]} for d in raw]
    elif engine == "world":
        dets = zs.detect_world(img)
    else:
        dets = zs.detect_florence(img)
    return dets, round((time.perf_counter() - t) * 1000)


def annotate(img, dets, engine):
    out = img.copy()
    h, w = out.shape[:2]
    col = COLORS[engine]
    for d in dets:
        x1, y1, x2, y2 = d["box"]
        p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
        cv2.rectangle(out, p1, p2, col, 2)
        cv2.putText(out, f'{d["confidence"]:.2f}', (p1[0] + 3, max(14, p1[1] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    cv2.putText(out, f"{engine} n={len(dets)}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    return out


def sheet(tiles, path, cols=4):
    rows = -(-len(tiles) // cols)
    th, tw = tiles[0].shape[:2]
    canvas = np.zeros((rows * th, cols * tw, 3), np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        canvas[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = t
    cv2.imwrite(str(path), canvas)


def main():
    OUT.mkdir(exist_ok=True)
    pool = build_pool()
    print(f"pool: {len(pool)} frames", flush=True)
    import torch
    base_mb = torch.cuda.memory_allocated() // 2 ** 20 if torch.cuda.is_available() else 0

    friend = load_friend()
    vram = {"baseline": base_mb}
    if torch.cuda.is_available():
        vram["after_friend_load"] = torch.cuda.memory_allocated() // 2 ** 20
    zs.detect_world(pool[0][1])                                   # warm load
    if torch.cuda.is_available():
        vram["after_world_load"] = torch.cuda.memory_allocated() // 2 ** 20
    zs.load_florence()
    if torch.cuda.is_available():
        vram["after_florence_load"] = torch.cuda.memory_allocated() // 2 ** 20

    data = {}
    tiles = {e: [] for e in ENGINES}
    for name, img in pool:
        data[name] = {}
        for engine in ENGINES:
            dets, ms = run_engine(engine, friend, img)
            confs = [d["confidence"] for d in dets]
            data[name][engine] = {"n": len(dets), "mean_conf": round(sum(confs) / len(confs), 3) if confs else 0.0,
                                  "ms": ms, "boxes": [d["box"] for d in dets]}
            img_out = annotate(img, dets, engine)
            cv2.imwrite(str(OUT / f"{name}__{engine}.jpg"), img_out)
            tiles[engine].append(cv2.resize(img_out, (320, 180)))
            print(f"{name:>18} {engine:>8}: n={len(dets)} ms={ms}", flush=True)

    for engine in ENGINES:
        sheet(tiles[engine], OUT / f"sheet_{engine}.jpg")

    summary = {}
    for engine in ENGINES:
        ms = [data[n][engine]["ms"] for n in data]
        ns = [data[n][engine]["n"] for n in data]
        confs = [data[n][engine]["mean_conf"] for n in data if data[n][engine]["n"]]
        summary[engine] = {"avg_boxes": round(sum(ns) / len(ns), 2), "total_boxes": sum(ns),
                           "avg_conf": round(sum(confs) / len(confs), 3) if confs else 0.0,
                           "avg_ms": round(sum(ms) / len(ms)), "vram": vram}
    print("SUMMARY:", json.dumps(summary, indent=1), flush=True)

    (OUT / "gallery_data.json").write_text(json.dumps({"frames": data, "summary": summary,
                                                       "rotation_deg": ROT, "friend_conf": FRIEND_CONF},
                                                      indent=1), encoding="utf-8")

    rows = []
    for name, _ in pool:
        cols = "".join(f'<td><img src="{name}__{e}.jpg" width="420"><div class="cap">{e} '
                       f'n={data[name][e]["n"]} conf&asymp;{data[name][e]["mean_conf"]} '
                       f'{data[name][e]["ms"]}ms</div></td>' for e in ENGINES)
        rows.append(f'<tr><th>{name}</th>{cols}</tr>')
    html = ("<!doctype html><meta charset='utf-8'><title>Phase 2 A/B gallery</title>"
            "<style>body{font:14px sans-serif;background:#111;color:#eee}"
            "table{border-collapse:collapse}th{text-align:left;vertical-align:top;padding:6px}"
            "td{padding:4px}.cap{opacity:.85;padding-top:2px}"
            "h1{font-size:20px}b.w{color:#50dc50}b.f{color:#ff8c50}</style>"
            f"<h1>Phase 2 live-engine A/B - 12 frames x friend / <b class='w'>world</b> / <b class='f'>florence</b></h1>"
            f"<p>Frames: 5 owner captures (rotated {ROT}&deg; to upright per the C0 oracle) + test videos. "
            "Boxes are RAW engine output, drawn without the live sanitizer. "
            "Florence-2 has no per-box scores: conf is a fixed 0.50 placeholder.</p>"
            "<table>" + "".join(rows) + "</table>")
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print("wrote", OUT / "index.html", flush=True)


if __name__ == "__main__":
    main()

import cv2
import pandas as pd
import numpy as np
from ultralytics import YOLO
from collections import defaultdict

MODEL_PATH = "runs/segment/runs/aquaculture/tilapia_seg/weights/best.pt"
VIDEO_PATH = "test_videos/tilapia_clear.mp4"
OUTPUT_CSV = "fish_movement_features.csv"

model = YOLO(MODEL_PATH)
cap = cv2.VideoCapture(VIDEO_PATH)

if not cap.isOpened():
    raise RuntimeError(f"Could not open video: {VIDEO_PATH}")

fps = cap.get(cv2.CAP_PROP_FPS)
fps = fps if fps > 0 else 30.0

history = defaultdict(list)
rows = []
frame_no = 0

while True:
    ok, frame = cap.read()
    if not ok:
        break

    frame_no += 1
    result = model.track(
        source=frame,
        tracker="bytetrack.yaml",
        persist=True,
        conf=0.35,
        imgsz=640,
        device=0,
        verbose=False
    )[0]

    if result.boxes is None or result.boxes.id is None:
        continue

    boxes = result.boxes.xyxy.cpu().numpy()
    ids = result.boxes.id.int().cpu().numpy()
    scores = result.boxes.conf.cpu().numpy()

    for box, track_id, confidence in zip(boxes, ids, scores):
        x1, y1, x2, y2 = box
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2

        history[track_id].append((frame_no, cx, cy))
        previous = history[track_id][-2] if len(history[track_id]) >= 2 else None

        displacement = 0.0
        speed_px_sec = 0.0

        if previous is not None:
            frame_gap = frame_no - previous[0]
            displacement = float(np.hypot(cx - previous[1], cy - previous[2]))
            speed_px_sec = displacement * fps / frame_gap

        rows.append({
            "frame": frame_no,
            "time_sec": frame_no / fps,
            "track_id": int(track_id),
            "center_x": float(cx),
            "center_y": float(cy),
            "displacement_px": displacement,
            "speed_px_sec": speed_px_sec,
            "confidence": float(confidence),
            "track_duration_sec": len(history[track_id]) / fps
        })

    if frame_no % 50 == 0:
        print(f"Processed {frame_no} frames")

cap.release()

df = pd.DataFrame(rows)
df.to_csv(OUTPUT_CSV, index=False)

print("\nFeature extraction complete!")
print("Frames processed:", frame_no)
print("Tracked observations:", len(df))
print("Unique track IDs:", df["track_id"].nunique() if not df.empty else 0)
print("CSV saved to:", OUTPUT_CSV)
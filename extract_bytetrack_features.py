import cv2
import pandas as pd
import numpy as np
from ultralytics import YOLO

VIDEO = "test_videos/tilapia_clear.mp4"
MODEL = "runs/segment/runs/aquaculture/tilapia_seg/weights/best.pt"
OUTPUT = "fish_movement_features_bytetrack.csv"

# Gaps larger than this are not used for speed calculations
MAX_SPEED_GAP_FRAMES = 3

model = YOLO(MODEL)
cap = cv2.VideoCapture(VIDEO)

if not cap.isOpened():
    raise RuntimeError(f"Cannot open video: {VIDEO}")

fps = cap.get(cv2.CAP_PROP_FPS)
if not np.isfinite(fps) or fps <= 0:
    cap.release()
    raise RuntimeError("Invalid video FPS; unable to calculate movement.")

total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

print(f"Video FPS: {fps:.3f}")
print(f"Video frames: {total_frames}")
print(f"Duration: {total_frames / fps:.2f} seconds")

rows = []
previous = {}
frame_no = 0

while True:
    ok, frame = cap.read()
    if not ok:
        break

    results = model.track(
        frame,
        persist=True,
        tracker="bytetrack.yaml",
        conf=0.20,
        iou=0.50,
        imgsz=640,
        device=0,
        verbose=False
    )

    result = results[0]
    boxes = result.boxes

    if boxes is not None and boxes.id is not None:
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.int().cpu().numpy()
        confs = boxes.conf.cpu().numpy()

        for box, track_id, confidence in zip(xyxy, ids, confs):
            x1, y1, x2, y2 = box
            cx = float((x1 + x2) / 2)
            cy = float((y1 + y2) / 2)
            track_id = int(track_id)

            old = previous.get(track_id)
            frame_gap = (
                frame_no - old["frame"] if old is not None else 0
            )

            displacement = np.nan
            speed = np.nan
            gap_seconds = np.nan
            speed_valid = False

            if old is not None and frame_gap > 0:
                displacement = float(
                    np.hypot(cx - old["x"], cy - old["y"])
                )
                gap_seconds = frame_gap / fps

                if frame_gap <= MAX_SPEED_GAP_FRAMES:
                    speed = displacement / gap_seconds
                    speed_valid = True

            rows.append({
                "frame": frame_no,
                "time_sec": frame_no / fps,
                "track_id": track_id,
                "center_x": cx,
                "center_y": cy,
                "frame_gap": frame_gap,
                "gap_seconds": gap_seconds,
                "displacement_px": displacement,
                "speed_px_sec": speed,
                "speed_valid": speed_valid,
                "confidence": float(confidence)
            })

            # Keep the most recent observation even after a long gap.
            # The gap itself will not produce a valid speed.
            previous[track_id] = {
                "frame": frame_no,
                "x": cx,
                "y": cy
            }

    frame_no += 1

cap.release()

df = pd.DataFrame(rows)

if df.empty:
    print("No tracked detections found. Check model/video paths.")
else:
    df.to_csv(OUTPUT, index=False)

    valid = df[df["speed_valid"]]
    gaps = df[df["frame_gap"] > MAX_SPEED_GAP_FRAMES]

    print("\n--- Movement Extraction Report ---")
    print("Frames processed:", frame_no)
    print("Observations:", len(df))
    print("Unique track IDs:", df["track_id"].nunique())
    print("Valid speed observations:", len(valid))
    print("Observations after long gaps:", len(gaps))
    print("Invalid-speed observations:", int((~df["speed_valid"]).sum()))
    print("Saved:", OUTPUT)
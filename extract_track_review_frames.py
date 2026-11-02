import cv2
import pandas as pd
from pathlib import Path

VIDEO = Path("runs/segment/track-3/tilapia_clear.avi")
CSV = Path("fish_movement_features_bytetrack.csv")
OUTPUT = Path("track_review_frames")
TARGET_IDS = [1, 2, 4, 37, 84]

# Select observations near the start, middle, and end of each track.
df = pd.read_csv(CSV)

required = {"frame", "time_sec", "track_id"}
if not required.issubset(df.columns):
    raise ValueError(f"CSV must contain columns: {required}")

if not VIDEO.exists():
    raise FileNotFoundError(f"Video not found: {VIDEO}")

OUTPUT.mkdir(exist_ok=True)

cap = cv2.VideoCapture(str(VIDEO))
if not cap.isOpened():
    raise RuntimeError(f"Cannot open video: {VIDEO}")

fps = cap.get(cv2.CAP_PROP_FPS)
if fps <= 0:
    raise RuntimeError("Invalid video FPS")

saved = []
for tid in TARGET_IDS:
    track = df[df["track_id"] == tid].sort_values("frame")
    if track.empty:
        print(f"Track {tid}: not found in CSV")
        continue

    positions = sorted(set([
        0,
        len(track) // 2,
        len(track) - 1
    ]))

    for pos in positions:
        row = track.iloc[pos]
        frame_no = int(row["frame"])
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()

        if not ok:
            print(f"Could not read frame {frame_no}")
            continue

        seconds = frame_no / fps
        filename = f"id_{tid}_frame_{frame_no:04d}_{seconds:.2f}s.jpg"
        path = OUTPUT / filename

        cv2.putText(
            frame,
            f"Review ID {tid} | Frame {frame_no} | {seconds:.2f}s",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2
        )

        cv2.imwrite(str(path), frame)
        saved.append({
            "track_id": tid,
            "frame": frame_no,
            "time_sec": round(seconds, 3),
            "image": str(path)
        })

cap.release()

pd.DataFrame(saved).to_csv(
    OUTPUT / "review_frame_index.csv", index=False
)

print(f"Saved {len(saved)} review frames to: {OUTPUT}")
print("Index: track_review_frames/review_frame_index.csv")
import argparse
from pathlib import Path

import cv2
import joblib
import numpy as np
import pandas as pd
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
DETECTOR = ROOT / "runs/segment/runs/aquaculture/tilapia_seg/weights/best.pt"
BEHAVIOR_MODEL = ROOT / "behavior_random_forest.joblib"
MAX_SPEED_GAP_FRAMES = 3


def validated_fps(fps):
    """Return the video's real FPS or raise; never guess a value."""
    if fps is None or not np.isfinite(fps) or fps <= 0:
        raise RuntimeError("Video FPS is unavailable or invalid; refusing to guess it.")
    return float(fps)


def movement_step(old, frame, x, y, fps):
    """(displacement_px, speed_px_sec) from the previous observation of the same track.
    NaN for a track's first observation or after a gap > MAX_SPEED_GAP_FRAMES."""
    if old is None or not 0 < frame - old["frame"] <= MAX_SPEED_GAP_FRAMES:
        return np.nan, np.nan
    displacement = float(np.hypot(x - old["x"], y - old["y"]))
    return displacement, displacement / ((frame - old["frame"]) / fps)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Path to input video")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.is_absolute():
        video = ROOT / video

    if not video.is_file():
        raise FileNotFoundError(f"Video not found: {video}")
    if not DETECTOR.is_file():
        raise FileNotFoundError(f"YOLO model not found: {DETECTOR}")
    if not BEHAVIOR_MODEL.is_file():
        raise FileNotFoundError(f"Behavior model not found: {BEHAVIOR_MODEL}")

    package = joblib.load(BEHAVIOR_MODEL)
    classifier = package["model"]
    features = package["features"]
    detector = YOLO(str(DETECTOR))

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    fps = validated_fps(fps)

    rows = []
    previous = {}
    frame_number = 0

    # Persist tracker IDs across frames.
    results = detector.track(
        source=str(video),
        stream=True,
        persist=True,
        tracker="botsort.yaml",
        imgsz=640,
        conf=0.35,
        device=0,
        save=True,
        show=False,
        verbose=False,
    )

    for result in results:
        frame_number += 1
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            continue

        ids = boxes.id.int().cpu().tolist()
        xy = boxes.xywh.cpu().numpy()
        confidences = boxes.conf.cpu().numpy()

        for track_id, box, confidence in zip(ids, xy, confidences):
            center_x, center_y = float(box[0]), float(box[1])
            old = previous.get(track_id)

            displacement, speed = movement_step(old, frame_number, center_x, center_y, fps)

            previous[track_id] = {
                "frame": frame_number, "x": center_x, "y": center_y
            }

            rows.append({
                "frame": frame_number,
                "time_sec": (frame_number - 1) / fps,
                "track_id": int(track_id),
                "center_x": center_x,
                "center_y": center_y,
                "displacement_px": displacement,
                "speed_px_sec": speed,
                "confidence": float(confidence),
            })

    if not rows:
        raise RuntimeError(
            "No tracked fish found. Check the video and detector output."
        )

    movement = pd.DataFrame(rows)
    movement.to_csv(ROOT / "fish_movement_features.csv", index=False)

    # Match the same feature construction used by the existing model.
    movement["tracking_jump"] = movement["speed_px_sec"] > 500
    movement["clean_speed"] = movement["speed_px_sec"].where(
        ~movement["tracking_jump"], np.nan
    )

    summary = movement.groupby("track_id").agg(
        observations=("frame", "count"),
        duration_sec=("time_sec", lambda s: s.max() - s.min() + 1 / fps),
        mean_speed_px_sec=("clean_speed", "mean"),
        median_speed_px_sec=("clean_speed", "median"),
        speed_variation=("clean_speed", "std"),
        mean_confidence=("confidence", "mean"),
        tracking_jumps=("tracking_jump", "sum"),
    ).reset_index()

    # The trained model expects these exact names.
    X = summary[features].copy()
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0)

    valid = (
        (summary["observations"] >= 30)
        & (summary["tracking_jumps"] <= 3)
        & (summary["mean_confidence"] >= 0.50)
    )

    summary["predicted_behavior"] = "insufficient_data"
    if valid.any():
        summary.loc[valid, "predicted_behavior"] = classifier.predict(
            X.loc[valid]
        )

    summary["review_tracking"] = ~valid
    summary.to_csv(ROOT / "fish_behavior_analysis.csv", index=False)

    summary[[
        "track_id", "observations", "duration_sec",
        "mean_speed_px_sec", "predicted_behavior", "review_tracking"
    ]].to_csv(ROOT / "fish_behavior_predictions.csv", index=False)

    print("\nVideo analysis complete!")
    print("Frames processed:", frame_number)
    print("Tracks found:", len(summary))
    print("\nBehavior predictions:")
    print(summary["predicted_behavior"].value_counts().to_string())
    print("\nSaved: fish_movement_features.csv")
    print("Saved: fish_behavior_analysis.csv")
    print("Saved: fish_behavior_predictions.csv")
    print("Annotated video is saved by Ultralytics; check its printed output path.")
    print("Behavior categories are provisional, not fish-health diagnoses.")


if __name__ == "__main__":
    main()
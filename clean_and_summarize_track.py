import pandas as pd
import numpy as np

INPUT = "fish_movement_features_bytetrack.csv"
CLEAN_OUTPUT = "fish_movement_features_clean.csv"
SUMMARY_OUTPUT = "fish_track_quality_summary.csv"
REVIEW_OUTPUT = "fish_behavior_review.csv"

import cv2

VIDEO = "test_videos/tilapia_clear.mp4"
cap = cv2.VideoCapture(VIDEO)
FPS = cap.get(cv2.CAP_PROP_FPS)
cap.release()

if FPS <= 0:
    raise ValueError("Could not read the video's FPS")

print(f"Using actual video FPS: {FPS:.3f}")

MIN_OBSERVATIONS = 30
MIN_CONFIDENCE = 0.45
MAX_SPEED_PX_SEC = 500.0

df = pd.read_csv(INPUT)
required = {
    "frame", "time_sec", "track_id",
    "center_x", "center_y", "confidence"
}
missing = required - set(df.columns)
if missing:
    raise ValueError(f"Missing columns: {sorted(missing)}")

df = df.sort_values(["track_id", "frame"]).copy()

# Recompute movement only across consecutive frames.
# Never calculate displacement across a tracking gap.
group = df.groupby("track_id", sort=False)
previous_frame = group["frame"].shift(1)
previous_x = group["center_x"].shift(1)
previous_y = group["center_y"].shift(1)

consecutive = (df["frame"] - previous_frame) == 1
dx = df["center_x"] - previous_x
dy = df["center_y"] - previous_y

df["frame_gap"] = df["frame"] - previous_frame
df["displacement_px_clean"] = np.where(
    consecutive, np.hypot(dx, dy), np.nan
)
df["speed_px_sec_clean"] = (
    df["displacement_px_clean"] * FPS
)

# Flag suspicious speeds; retain original values for audit.
df["suspicious_jump"] = (
    df["speed_px_sec_clean"] > MAX_SPEED_PX_SEC
)
df["speed_px_sec_clean"] = df["speed_px_sec_clean"].mask(
    df["suspicious_jump"]
)

df["tracking_gap"] = (
    df["frame_gap"].notna() & (df["frame_gap"] > 1)
)


df["missing_frames"] = (
    (df["frame_gap"] - 1).clip(lower=0)
    .where(df["tracking_gap"], 0)
)

df["gap_duration_sec"] = df["missing_frames"] / FPS

df.to_csv(CLEAN_OUTPUT, index=False)

# Summarize track duration, confidence, coverage and movement.
summary = df.groupby("track_id").agg(
    observations=("frame", "count"),
    first_frame=("frame", "min"),
    last_frame=("frame", "max"),
    mean_confidence=("confidence", "mean"),
    median_speed_px_sec=("speed_px_sec_clean", "median"),
    max_clean_speed_px_sec=("speed_px_sec_clean", "max"),
    suspicious_jumps=("suspicious_jump", "sum"),
    tracking_gaps=("tracking_gap", "sum"),
    missing_frames=("missing_frames", "sum"),
    max_gap_frames=("frame_gap", lambda s: max(
        0, s.max() - 1
    ) if s.notna().any() else 0),
).reset_index()

summary["missing_time_sec"] = summary["missing_frames"] / FPS
summary["max_gap_sec"] = summary["max_gap_frames"] / FPS

summary["duration_sec"] = (
    summary["last_frame"] - summary["first_frame"]
) / FPS + 1 / FPS

summary["frame_span"] = (
    summary["last_frame"] - summary["first_frame"] + 1
)
summary["coverage_pct"] = (
    100 * summary["observations"] / summary["frame_span"]
)

# Conservative data-quality rules, not health classifications.
summary["review_reasons"] = summary.apply(
    lambda r: "; ".join(
        reason for condition, reason in [
            (r["observations"] < MIN_OBSERVATIONS,
             "short track"),
            (r["mean_confidence"] < MIN_CONFIDENCE,
             "low mean confidence"),
            (r["coverage_pct"] < 70,
             "low frame coverage"),
            (r["suspicious_jumps"] > max(
                3, 0.10 * r["observations"]
            ), "many suspicious speed jumps"),
        ] if condition
    ) or "No automatic quality flag",
    axis=1
)

summary["review_tracking"] = (
    summary["review_reasons"] != "No automatic quality flag"
)
summary["behavior_status"] = np.where(
    summary["review_tracking"],
    "insufficient_data_or_review",
    "data_available_behavior_unvalidated"
)

summary.to_csv(SUMMARY_OUTPUT, index=False)

# Preserve any existing model predictions only as unvalidated reference.
try:
    predictions = pd.read_csv("fish_behavior_predictions.csv")
    if "track_id" in predictions.columns:
        keep = [
            c for c in ["track_id", "predicted_behavior"]
            if c in predictions.columns
        ]
        review = summary.merge(
            predictions[keep], on="track_id", how="left"
        )
        review = review.rename(
            columns={"predicted_behavior":
                     "unvalidated_model_prediction"}
        )
    else:
        review = summary.copy()
except FileNotFoundError:
    review = summary.copy()

review.to_csv(REVIEW_OUTPUT, index=False)

print("\nTRACK QUALITY REPORT")
print("Tracks:", len(summary))
print("Tracks needing review:", int(summary["review_tracking"].sum()))
print("Tracks with >=30 observations:",
      int((summary["observations"] >= 30).sum()))
print("Tracks with >=100 observations:",
      int((summary["observations"] >= 100).sum()))
print("Suspicious speed observations:",
      int(df["suspicious_jump"].sum()))
print("Tracking gaps:", int(df["tracking_gap"].sum()))

print("\nReview reasons:")
print(summary["review_reasons"].value_counts().to_string())

print("\nSaved files:")
print(CLEAN_OUTPUT)
print(SUMMARY_OUTPUT)
print(REVIEW_OUTPUT)
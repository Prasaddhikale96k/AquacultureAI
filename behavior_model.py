import pandas as pd
import numpy as np
import joblib

INPUT_CSV = "fish_movement_features.csv"
OUTPUT_CSV = "fish_behavior_analysis.csv"
PREDICTIONS_CSV = "fish_behavior_predictions.csv"
MODEL_PATH = "behavior_random_forest.joblib"

# Load movement observations and trained model
df = pd.read_csv(INPUT_CSV)
saved = joblib.load(MODEL_PATH)
model = saved["model"]
features = saved["features"]

# Detect suspicious jumps and exclude them from speed calculations
df["tracking_jump"] = df["speed_px_sec"] > 500
df["clean_speed"] = df["speed_px_sec"].where(
    ~df["tracking_jump"], np.nan
)

# Real FPS implied by the file itself (frame spacing / time spacing); no guessed value.
_d = df.sort_values(["track_id", "frame"]).groupby("track_id")[["frame", "time_sec"]].diff()
_d = _d[(_d["frame"] > 0) & (_d["time_sec"] > 0)]
FPS = float((_d["frame"] / _d["time_sec"]).median())
if not np.isfinite(FPS) or FPS <= 0:
    raise ValueError("Cannot derive FPS from the movement file; refusing to guess it.")

# Summarize tracks
summary = df.groupby("track_id").agg(
    observations=("frame", "count"),
    duration_sec=("time_sec", lambda s: s.max() - s.min() + 1 / FPS),
    mean_speed_px_sec=("clean_speed", "mean"),
    median_speed_px_sec=("clean_speed", "median"),
    speed_variation=("clean_speed", "std"),
    mean_confidence=("confidence", "mean"),
    tracking_jumps=("tracking_jump", "sum"),
).reset_index()

# Match the exact feature names expected by the trained model
X = summary[features].copy()

# Avoid unsupported predictions from very short tracks
valid = (
    (summary["observations"] >= 30)
    & (summary["tracking_jumps"] <= 3)
    & (summary["mean_confidence"] >= 0.50)
)

summary["predicted_behavior"] = "insufficient_data"

if valid.any():
    X_valid = X.loc[valid].copy()
    X_valid = X_valid.replace([np.inf, -np.inf], np.nan).fillna(0)
    summary.loc[valid, "predicted_behavior"] = model.predict(X_valid)

summary["review_tracking"] = ~valid

summary.to_csv(OUTPUT_CSV, index=False)

# Export predictions for convenient review
summary[[
    "track_id", "observations", "duration_sec",
    "mean_speed_px_sec", "predicted_behavior", "review_tracking"
]].to_csv(PREDICTIONS_CSV, index=False)

print("Behavior analysis complete!")
print("Tracks analyzed:", len(summary))
print("\nPredictions:")
print(summary["predicted_behavior"].value_counts().to_string())
print("\nTracks flagged for review:", int(summary["review_tracking"].sum()))
print("Saved:", OUTPUT_CSV)
print("Saved:", PREDICTIONS_CSV)
print("\nNote: Predictions are provisional activity categories,")
print("not verified diagnoses of fish health.")
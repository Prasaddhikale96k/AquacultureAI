"""Experimental zebrafish movement-classifier integration helpers.

IMPORTANT COMPATIBILITY LIMIT
The classifier was trained on 60-frame windows of 8 zebrafish pose keypoints
(see extract_behavior_features.py). Live tilapia tracking (ByteTrack/YOLO-seg)
provides ONE box centre per fish. Only 8 of the 20 training features can be
computed from a centroid track; the other 12 need the 8 keypoints. This module
therefore never produces a prediction from centroid-only tracking. A prediction
is produced only when all 20 features are supplied (e.g. from a real 8-keypoint
window), and it is not validated for tilapia or fish-health prediction.
"""
from collections import deque
from pathlib import Path

import joblib
import numpy as np

from extract_behavior_features import features as keypoint_features

ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "runs" / "behavior_baseline" / "random_forest_baseline.joblib"
WINDOW = 60

# Feature names/order exactly as produced by the training extractor.
_probe = np.random.default_rng(0).normal(size=(WINDOW, 8, 2)).cumsum(axis=0)
EXPECTED_FEATURES = list(keypoint_features(_probe))
CENTROID_FEATURES = [
    "centroid_speed_mean", "centroid_speed_max", "centroid_speed_std",
    "net_displacement", "path_length", "straightness",
    "movement_variability_cv", "frac_frames_moving",
]
KEYPOINT_ONLY_FEATURES = [f for f in EXPECTED_FEATURES if f not in CENTROID_FEATURES]

WARNING = ("Experimental: this model was trained on zebrafish experimental data (60-frame keypoint windows). "
           "It is not validated for tilapia or for fish-health risk prediction.")


# ------------------------------------------------------------------ model
def load_model(path=MODEL_PATH):
    """Return (bundle, error). Never raises. The file is the project's own artifact (joblib/pickle):
    only load files you trust."""
    path = Path(path)
    if not path.is_file():
        return None, f"Model file not found: {path}"
    try:
        bundle = joblib.load(path)
    except Exception as e:
        return None, f"Model could not be loaded: {type(e).__name__}: {e}"
    if not isinstance(bundle, dict) or not {"model", "feature_columns", "classes"} <= set(bundle):
        return None, "Model file has an unexpected structure (needs model, feature_columns, classes)."
    if list(bundle["feature_columns"]) != EXPECTED_FEATURES:
        return None, "Model feature names/order do not match the training extractor; refusing to use it."
    if not hasattr(bundle["model"], "predict_proba"):
        return None, "Model lacks predict_proba."
    return bundle, None


# ------------------------------------------------------------------ windows
class TrackWindowBuffer:
    """Per-track rolling window of consecutive-frame centroids. Observations of different
    track IDs are never mixed, and a gap (missing frame), repeat or backwards frame restarts that track's window."""

    def __init__(self, window=WINDOW):
        self.window = window
        self._buf = {}
        self._last = {}
        self.resets = {}

    def update(self, track_id, frame, x, y):
        tid, frame = int(track_id), int(frame)
        last = self._last.get(tid)
        if last is not None and frame != last + 1:
            self._buf[tid].clear()
            self.resets[tid] = self.resets.get(tid, 0) + 1
        self._buf.setdefault(tid, deque(maxlen=self.window)).append((float(x), float(y)))
        self._last[tid] = frame

    def n_obs(self, track_id):
        return len(self._buf.get(int(track_id), ()))

    def is_complete(self, track_id):
        return self.n_obs(track_id) == self.window

    def window_xy(self, track_id):
        return np.array(self._buf.get(int(track_id), ()), dtype=np.float64).reshape(-1, 2)


def centroid_features(xy):
    """The 8 training features computable from a centroid track (same formulas as the training code)."""
    xy = np.asarray(xy, dtype=np.float64)
    if xy.shape != (WINDOW, 2) or not np.isfinite(xy).all():
        raise ValueError(f"Need a finite ({WINDOW}, 2) centroid window, got {xy.shape}")
    step = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    path, net, eps = step.sum(), np.linalg.norm(xy[-1] - xy[0]), 1e-9
    return {
        "centroid_speed_mean": step.mean(), "centroid_speed_max": step.max(), "centroid_speed_std": step.std(),
        "net_displacement": net, "path_length": path, "straightness": net / (path + eps),
        "movement_variability_cv": step.std() / (step.mean() + eps), "frac_frames_moving": (step > 1.0).mean(),
    }


# ------------------------------------------------------------------ classification
def _result(status, message, **kw):
    out = {"status": status, "message": message, "prediction": None, "probabilities": None,
           "n_obs": None, "missing_features": [], "warning": WARNING}
    out.update(kw)
    return out


def classify_features(bundle, feats, n_obs=WINDOW):
    """Predict from a complete dict of all 20 features. No imputation, ever."""
    if bundle is None:
        return _result("model_unavailable", "Classifier is not loaded.", n_obs=n_obs)
    if n_obs < WINDOW:
        return _result("insufficient_window", f"Only {n_obs}/{WINDOW} consecutive observations.", n_obs=n_obs)
    cols = list(bundle["feature_columns"])
    missing = [c for c in cols if c not in (feats or {})]
    if missing:
        return _result("features_incompatible", f"{len(missing)} required feature(s) missing.",
                       n_obs=n_obs, missing_features=missing)
    row = np.array([[feats[c] for c in cols]], dtype=np.float64)
    if not np.isfinite(row).all():
        return _result("invalid_features", "Non-finite feature value(s); no prediction made.", n_obs=n_obs)
    proba = bundle["model"].predict_proba(row)[0]
    classes = list(bundle["model"].classes_)
    return _result("ok", "Prediction from a complete 20-feature window.", n_obs=n_obs,
                   prediction=classes[int(np.argmax(proba))],
                   probabilities={c: float(p) for c, p in zip(classes, proba)})


def classify_centroid_window(bundle, xy, n_obs=None):
    """Live ByteTrack input (centroid only). Always refuses to predict: 12 of 20 features need 8 keypoints."""
    n = len(xy) if n_obs is None else n_obs
    if bundle is None:
        return _result("model_unavailable", "Classifier is not loaded.", n_obs=n)
    if n < WINDOW:
        return _result("insufficient_window", f"Only {n}/{WINDOW} consecutive observations.", n_obs=n)
    try:
        partial = centroid_features(xy)
    except ValueError as e:
        return _result("invalid_features", str(e), n_obs=n)
    return classify_features(bundle, partial, n_obs=n) | {"partial_features": partial}

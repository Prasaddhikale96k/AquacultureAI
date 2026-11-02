"""Extract movement features from the prepared zebrafish keypoint arrays.

Reads dataset/zebrafish_behavior_prepared/clean_training_samples.csv and the .npy
files it points to. Frame rate and coordinate units are undocumented, so every
speed/length is in coordinate units (per frame). Features use frame-to-frame
changes and centred coordinates only; position, well, experiment and folder
information is kept as metadata columns and is NOT a feature.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
PREP = ROOT / "dataset" / "zebrafish_behavior_prepared"
INPUT = PREP / "clean_training_samples.csv"
OUTPUT = PREP / "behavior_features.csv"
EXPECTED_SHAPE = (60, 8, 2)

META_COLS = ["feature_path", "clip_path", "normalized_label", "well_id", "group_id",
             "experiment_group", "frame_start", "frame_end"]
IU = np.triu_indices(8, 1)


def features(a):
    """a: (60, 8, 2) float array -> dict of units/frame features."""
    c = a.mean(axis=1)                                   # centroid per frame (T,2)
    step_c = np.linalg.norm(np.diff(c, axis=0), axis=1)  # centroid speed (T-1)
    step_p = np.linalg.norm(np.diff(a, axis=0), axis=2)  # per-point speed (T-1, 8)
    centred = a - c[:, None, :]                          # centred coordinates
    spread = np.sqrt((centred ** 2).sum(axis=2).mean(axis=1))
    dist = np.linalg.norm(centred[:, :, None] - centred[:, None], axis=3)[:, IU[0], IU[1]]  # (T,28)
    d_dist = np.abs(np.diff(dist, axis=0))               # pairwise-distance change per frame
    pt_mean = step_p.mean(axis=1)                        # mean point speed per frame
    # change in centred shape between frames (independent of global translation)
    shape_change = np.linalg.norm(np.diff(centred, axis=0), axis=2).mean(axis=1)
    eps = 1e-9
    path = step_c.sum()
    net = np.linalg.norm(c[-1] - c[0])
    return {
        "centroid_speed_mean": step_c.mean(),
        "centroid_speed_max": step_c.max(),
        "centroid_speed_std": step_c.std(),
        "keypoint_speed_mean": step_p.mean(),
        "keypoint_speed_max": step_p.max(),
        "keypoint_speed_std_across_points": step_p.mean(axis=0).std(),
        "keypoint_speed_std_over_time": pt_mean.std(),
        "spread_mean": spread.mean(),
        "spread_std": spread.std(),
        "spread_range": spread.max() - spread.min(),
        "pairdist_change_mean": d_dist.mean(),
        "pairdist_change_max": d_dist.max(),
        "pairdist_change_std": d_dist.std(),
        "pairdist_temporal_std_mean": dist.std(axis=0).mean(),
        "shape_change_mean": shape_change.mean(),
        "net_displacement": net,
        "path_length": path,
        "straightness": net / (path + eps),
        "movement_variability_cv": step_c.std() / (step_c.mean() + eps),
        "frac_frames_moving": (step_c > 1.0).mean(),   # threshold in coord units/frame (arbitrary, unverified)
    }


def main():
    if not INPUT.exists():
        raise SystemExit(f"Missing input: {INPUT}")
    meta = pd.read_csv(INPUT)
    missing = [c for c in META_COLS if c not in meta.columns]
    if missing:
        raise SystemExit(f"{INPUT} lacks columns: {missing}")

    rows, skipped = [], []
    for _, r in meta.iterrows():
        p = ROOT / r["feature_path"]
        try:
            a = np.load(p, allow_pickle=False)
        except Exception as e:
            skipped.append((r["feature_path"], f"unreadable: {e}"))
            continue
        if a.shape != EXPECTED_SHAPE:
            skipped.append((r["feature_path"], f"shape {a.shape}"))
            continue
        a = a.astype(np.float64)
        if not np.isfinite(a).all():
            skipped.append((r["feature_path"], "NaN/Inf"))
            continue
        f = features(a)
        if not all(np.isfinite(v) for v in f.values()):
            skipped.append((r["feature_path"], "non-finite feature"))
            continue
        rows.append({**{k: r[k] for k in META_COLS}, **f})

    if not rows:
        raise SystemExit("No valid samples; nothing written.")
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT, index=False)
    n_feat = out.shape[1] - len(META_COLS)
    print(f"Samples read: {len(meta)}  written: {len(out)}  skipped: {len(skipped)}")
    for s in skipped[:10]:
        print("  skipped:", s)
    print(f"Features: {n_feat}  (speeds are coordinate units per frame; frame rate/units unverified)")
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    main()

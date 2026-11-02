"""Run the tracking-review tasks in order (no retraining, no dashboard changes).

1. Corrected movement features + track-quality summary
2. Reviewed track validation
3. Manual behavior review sheet (labels left blank)

Original files are never modified. Inputs are re-read from the existing
tracking CSV; the video is only used for its real FPS and for review frames.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

# Use the project's .venv interpreter.
if VENV_PY.exists() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
    sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve())] + sys.argv[1:]))

import cv2
import numpy as np
import pandas as pd

os.chdir(ROOT)

VIDEO = Path("test_videos/tilapia_clear.mp4")
TRACK_CSV = Path("fish_movement_features_bytetrack.csv")
SUMMARY_IN = Path("fish_track_quality_summary.csv")
VALIDATION_IN = Path("track_validation.csv")
REVIEW_DIR = Path("track_review_frames")
REVIEW_INDEX_IN = REVIEW_DIR / "review_frame_index.csv"

FEATURES_OUT = Path("fish_movement_features_bytetrack_corrected.csv")
SUMMARY_OUT = Path("fish_track_quality_summary_corrected.csv")
VALIDATION_OUT = Path("track_validation_reviewed.csv")
BEHAVIOR_OUT = Path("behavior_manual_review.csv")
BEHAVIOR_BACKUP = Path("behavior_manual_review_previous.csv")
BEHAVIOR_FRAMES_DIR = Path("behavior_review_frames")
BEHAVIOR_INDEX_OUT = BEHAVIOR_FRAMES_DIR / "behavior_review_frame_index.csv"

TARGET_IDS = [1, 2, 4, 37, 84]
MAX_SPEED_GAP_FRAMES = 3
MAX_SPEED_PX_SEC = 500.0      # same threshold as clean_and_summarize_track.py
MIN_OBSERVATIONS = 30
MIN_CONFIDENCE = 0.45
MIN_COVERAGE_PCT = 70
SAMPLES_PER_TRACK = 8

INSTRUCTION = ("Assess movement across MULTIPLE frames (use the contact sheet and "
               "the continuous segment, ideally play the video), never from a single "
               "image. Describe observable movement only; do not infer health, "
               "stress, or abnormality.")

errors = []


class PipelineStop(Exception):
    pass


def require(cond, msg):
    if not cond:
        raise PipelineStop(msg)


def read_csv(path, required):
    require(path.exists(), f"Missing input file: {path}")
    try:
        df = pd.read_csv(path)
    except Exception as e:
        raise PipelineStop(f"Cannot read {path}: {e}")
    missing = set(required) - set(df.columns)
    require(not missing, f"{path} lacks expected columns: {sorted(missing)}")
    return df


def get_fps():
    require(VIDEO.exists(), f"Video not found: {VIDEO}")
    cap = cv2.VideoCapture(str(VIDEO))
    require(cap.isOpened(), f"Cannot open video: {VIDEO}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    require(np.isfinite(fps) and fps > 0, f"Video FPS unavailable for {VIDEO}; refusing to guess.")
    return float(fps), n


# --------------------------------------------------------------- Task 1
def task1(fps, n_frames):
    raw = read_csv(TRACK_CSV, ["frame", "track_id", "center_x", "center_y", "confidence"])
    require(not raw.duplicated(["track_id", "frame"]).any(), "Duplicate (track_id, frame) rows in tracking CSV")
    require(raw["frame"].between(0, n_frames - 1).all(), "Tracking CSV has frame numbers outside the video")
    for out in (FEATURES_OUT, SUMMARY_OUT):
        require(out.resolve() not in (TRACK_CSV.resolve(), SUMMARY_IN.resolve()), "Output would overwrite an original")

    df = raw.sort_values(["track_id", "frame"]).reset_index(drop=True)
    g = df.groupby("track_id", sort=False)
    prev_frame = g["frame"].shift(1)
    first = prev_frame.isna()

    df["time_sec"] = df["frame"] / fps
    df["is_first_observation"] = first
    df["frame_gap"] = (df["frame"] - prev_frame).fillna(0).astype(int)
    df["gap_seconds"] = df["frame_gap"] / fps
    df.loc[first, "gap_seconds"] = np.nan
    df["displacement_px"] = np.hypot(df["center_x"] - g["center_x"].shift(1),
                                     df["center_y"] - g["center_y"].shift(1))
    df["speed_valid"] = (~first) & (df["frame_gap"] >= 1) & (df["frame_gap"] <= MAX_SPEED_GAP_FRAMES)
    df["speed_px_sec"] = np.where(df["speed_valid"], df["displacement_px"] / df["gap_seconds"], np.nan)
    df["long_gap"] = df["frame_gap"] > MAX_SPEED_GAP_FRAMES
    df["suspicious_jump"] = df["speed_valid"] & (df["speed_px_sec"] > MAX_SPEED_PX_SEC)
    df["tracking_gap"] = df["frame_gap"] > 1
    df["missing_frames"] = (df["frame_gap"] - 1).clip(lower=0)
    df["fps_used"] = fps
    df.to_csv(FEATURES_OUT, index=False)

    # How the original file's speed fields compare (reported, not fixed in place)
    if {"speed_px_sec", "speed_valid"} <= set(raw.columns):
        m = raw.merge(df[["track_id", "frame", "speed_px_sec", "speed_valid"]],
                      on=["track_id", "frame"], suffixes=("_orig", ""))
        diff = int((m["speed_valid_orig"].astype(bool) != m["speed_valid"]).sum()
                   + ((m["speed_px_sec_orig"] - m["speed_px_sec"]).abs() > 1e-3).sum())
        print(f"[task1] original-vs-corrected speed field differences: {diff} row-field mismatches")

    speed_ok = df[df["speed_valid"] & ~df["suspicious_jump"]]
    agg = df.groupby("track_id").agg(
        observations=("frame", "count"),
        first_frame=("frame", "min"),
        last_frame=("frame", "max"),
        mean_confidence=("confidence", "mean"),
        suspicious_jumps=("suspicious_jump", "sum"),
        tracking_gaps=("tracking_gap", "sum"),
        long_gaps=("long_gap", "sum"),
        missing_frames=("missing_frames", "sum"),
        max_frame_gap=("frame_gap", "max"),
        max_valid_speed_px_sec=("speed_px_sec", "max"),
    )
    sp = speed_ok.groupby("track_id")["speed_px_sec"].agg(
        median_speed_px_sec="median", mean_speed_px_sec="mean", valid_speed_obs="count")
    s = agg.join(sp).reset_index()
    s["valid_speed_obs"] = s["valid_speed_obs"].fillna(0).astype(int)
    s["frame_span"] = s["last_frame"] - s["first_frame"] + 1
    s["duration_sec"] = s["frame_span"] / fps
    s["coverage_pct"] = 100 * s["observations"] / s["frame_span"]
    s["max_missing_run_frames"] = (s["max_frame_gap"] - 1).clip(lower=0)
    s["missing_time_sec"] = s["missing_frames"] / fps

    def reasons(r):
        out = [txt for c, txt in [
            (r.observations < MIN_OBSERVATIONS, "short track"),
            (r.mean_confidence < MIN_CONFIDENCE, "low mean confidence"),
            (r.coverage_pct < MIN_COVERAGE_PCT, "low frame coverage"),
            (r.suspicious_jumps > max(3, 0.10 * r.observations), "many suspicious speed jumps"),
            (r.long_gaps > 0, f"gap > {MAX_SPEED_GAP_FRAMES} frames"),
        ] if c]
        return "; ".join(out) or "No automatic quality flag"

    s["review_reasons"] = s.apply(reasons, axis=1)
    s["review_tracking"] = s["review_reasons"] != "No automatic quality flag"
    s["fps_used"] = fps
    s.to_csv(SUMMARY_OUT, index=False)
    print(f"[task1] wrote {FEATURES_OUT} ({len(df)} rows) and {SUMMARY_OUT} ({len(s)} tracks)")
    return df, s


# --------------------------------------------------------------- Task 2
NOTES = {
    1: ("provisional_pass",
        "Consistent in sampled review frames; provisional only, not full-frame verified."),
    2: ("provisional_pass",
        "Consistent in sampled review frames; provisional only, not full-frame verified."),
    4: ("manual_review_required",
        "Manual review required. Low confidence and gaps; box may include background."),
    37: ("manual_review_required",
         "Manual review required. Jumps and gaps reported; no identity switch has been visually confirmed."),
    84: ("manual_review_required",
         "Manual review required. Many speed jumps; no identity switch has been visually confirmed."),
}
LIMIT = ("Overlapping boxes and ambiguous fish/background regions limit confidence in the "
         "sampled review; sampled still frames cannot confirm or rule out identity switches.")


def task2(feat, summ):
    val = read_csv(VALIDATION_IN, ["track_id", "observations", "suspicious_jumps", "tracking_gaps", "notes"])
    idx = read_csv(REVIEW_INDEX_IN, ["track_id", "frame", "time_sec", "image"])
    require(VALIDATION_OUT.resolve() != VALIDATION_IN.resolve(), "Output would overwrite original validation")
    missing = [t for t in TARGET_IDS if t not in set(val["track_id"])]
    require(not missing, f"track_validation.csv lacks track IDs {missing}")

    out = val.copy()
    srow = summ.set_index("track_id")
    cols = ["review_status", "reviewed_frames", "corrected_suspicious_jumps", "corrected_tracking_gaps",
            "corrected_long_gaps", "corrected_max_frame_gap", "identity_switch_confirmed",
            "confidence_limitations", "review_update_notes"]
    for c in cols:
        out[c] = pd.Series([""] * len(out), index=out.index, dtype=object)
    for t in TARGET_IDS:
        i = out.index[out["track_id"] == t][0]
        status, note = NOTES[t]
        frames = sorted(idx.loc[idx["track_id"] == t, "frame"].astype(int))
        out.loc[i, "review_status"] = status
        out.loc[i, "reviewed_frames"] = ",".join(map(str, frames))
        if t in srow.index:
            out.loc[i, "corrected_suspicious_jumps"] = int(srow.at[t, "suspicious_jumps"])
            out.loc[i, "corrected_tracking_gaps"] = int(srow.at[t, "tracking_gaps"])
            out.loc[i, "corrected_long_gaps"] = int(srow.at[t, "long_gaps"])
            out.loc[i, "corrected_max_frame_gap"] = int(srow.at[t, "max_frame_gap"])
        out.loc[i, "identity_switch_confirmed"] = "no"
        out.loc[i, "confidence_limitations"] = LIMIT
        out.loc[i, "review_update_notes"] = note
    out.to_csv(VALIDATION_OUT, index=False)
    print(f"[task2] wrote {VALIDATION_OUT}")
    return out, idx


# --------------------------------------------------------------- Task 3
def pick_frames(frames, k):
    frames = list(frames)
    if len(frames) <= k:
        return frames
    pos = np.linspace(0, len(frames) - 1, k).round().astype(int)
    return [frames[p] for p in sorted(set(pos))]


def longest_run(frames):
    best = cur = (frames[0], frames[0])
    for f in frames[1:]:
        cur = (cur[0], f) if f == cur[1] + 1 else (f, f)
        if cur[1] - cur[0] > best[1] - best[0]:
            best = cur
    return best


def contact_sheet(cap, tid, track, frames, fps):
    tiles = []
    for f in frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, img = cap.read()
        require(ok, f"Cannot read frame {f} from {VIDEO}")
        r = track[track["frame"] == f].iloc[0]
        cv2.circle(img, (int(r.center_x), int(r.center_y)), 14, (0, 255, 255), 2)
        cv2.putText(img, f"ID {tid} frame {f} {f / fps:.2f}s", (8, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        tiles.append(img)
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    sheet = np.vstack(rows)
    scale = 1600 / sheet.shape[1]
    return cv2.resize(sheet, None, fx=scale, fy=scale) if scale < 1 else sheet


def task3(feat, summ, idx, fps):
    existing_new_schema = False
    if BEHAVIOR_OUT.exists():
        old = pd.read_csv(BEHAVIOR_OUT)
        if "review_notes" in old.columns and "suggested_frames" in old.columns:
            existing_new_schema = True
            require(old["behavior_label"].isna().all() or (old["behavior_label"].astype(str).str.strip() == "").all(),
                    f"{BEHAVIOR_OUT} already has manual behavior labels; refusing to overwrite")
        else:
            require(not BEHAVIOR_BACKUP.exists(),
                    f"{BEHAVIOR_OUT} has a different schema and {BEHAVIOR_BACKUP} already exists; not overwriting")
            shutil.copy2(BEHAVIOR_OUT, BEHAVIOR_BACKUP)
            print(f"[task3] existing {BEHAVIOR_OUT} (different schema) preserved as {BEHAVIOR_BACKUP}")

    BEHAVIOR_FRAMES_DIR.mkdir(exist_ok=True)
    cap = cv2.VideoCapture(str(VIDEO))
    require(cap.isOpened(), f"Cannot open video: {VIDEO}")
    s = summ.set_index("track_id")
    rows, index_rows = [], []
    for t in TARGET_IDS:
        require(t in s.index, f"Track {t} missing from corrected summary")
        track = feat[feat["track_id"] == t].sort_values("frame")
        obs_frames = track["frame"].astype(int).tolist()
        frames = pick_frames(obs_frames, SAMPLES_PER_TRACK)
        seg = longest_run(obs_frames)
        sheet_path = BEHAVIOR_FRAMES_DIR / f"id_{t}_contact_sheet.jpg"
        cv2.imwrite(str(sheet_path), contact_sheet(cap, t, track, frames, fps))
        reuse = idx[idx["track_id"] == t]
        reused_frames = set(reuse["frame"].astype(int))
        for f in frames:
            index_rows.append({"track_id": t, "frame": f, "time_sec": round(f / fps, 3),
                               "source": "existing_review_frame" if f in reused_frames else "sampled_observation",
                               "image": str(sheet_path)})
        for _, r in reuse.iterrows():
            index_rows.append({"track_id": t, "frame": int(r.frame), "time_sec": r.time_sec,
                               "source": "existing_review_image", "image": r.image})
        r = s.loc[t]
        rows.append({
            "track_id": t,
            "observation_count": int(r.observations),
            "first_frame": int(r.first_frame), "last_frame": int(r.last_frame),
            "duration_sec": round(r.duration_sec, 3),
            "median_speed_px_sec": round(r.median_speed_px_sec, 2),
            "mean_speed_px_sec": round(r.mean_speed_px_sec, 2),
            "mean_confidence": round(r.mean_confidence, 3),
            "suspicious_jumps": int(r.suspicious_jumps),
            "tracking_gaps": int(r.tracking_gaps),
            "long_gaps_over_3_frames": int(r.long_gaps),
            "max_frame_gap": int(r.max_frame_gap),
            "coverage_pct": round(r.coverage_pct, 1),
            "tracking_review_status": NOTES[t][0],
            "longest_continuous_segment": f"{seg[0]}-{seg[1]} ({(seg[1] - seg[0] + 1) / fps:.2f}s)",
            "suggested_frames": ";".join(map(str, frames)),
            "suggested_timestamps_sec": ";".join(f"{f / fps:.2f}" for f in frames),
            "existing_review_images": ";".join(reuse["image"].astype(str)),
            "contact_sheet": str(sheet_path),
            "review_instruction": INSTRUCTION,
            "behavior_label": "",
            "review_notes": "",
        })
    cap.release()
    pd.DataFrame(rows).to_csv(BEHAVIOR_OUT, index=False)
    pd.DataFrame(index_rows).drop_duplicates(["track_id", "frame", "source"]).to_csv(BEHAVIOR_INDEX_OUT, index=False)
    print(f"[task3] wrote {BEHAVIOR_OUT}, {BEHAVIOR_INDEX_OUT}, contact sheets in {BEHAVIOR_FRAMES_DIR}/")
    return pd.DataFrame(rows)


# --------------------------------------------------------------- checks
def checks(n_frames, feat):
    for p in (FEATURES_OUT, SUMMARY_OUT, VALIDATION_OUT, BEHAVIOR_OUT, BEHAVIOR_INDEX_OUT):
        require(len(pd.read_csv(p)) > 0, f"{p} is empty or unreadable")
    f = pd.read_csv(FEATURES_OUT)
    for c in ("frame_gap", "gap_seconds", "speed_valid"):
        require(c in f.columns, f"{FEATURES_OUT} lacks {c}")
    require(not f.loc[f["frame_gap"] > MAX_SPEED_GAP_FRAMES, "speed_valid"].any(), "speed marked valid across a long gap")
    b = pd.read_csv(BEHAVIOR_OUT, keep_default_na=False)
    for c in ("behavior_label", "review_notes", "review_instruction"):
        require(c in b.columns, f"{BEHAVIOR_OUT} lacks {c}")
    require((b["behavior_label"].astype(str).str.strip() == "").all(), "behavior labels were filled automatically")
    bi = pd.read_csv(BEHAVIOR_INDEX_OUT)
    require(bi["frame"].between(0, n_frames - 1).all(), "invalid frame number in behavior review index")
    obs = set(zip(feat["track_id"], feat["frame"]))
    sampled = bi[bi["source"] == "sampled_observation"]
    require(all((t, fr) in obs for t, fr in zip(sampled["track_id"], sampled["frame"])), "sampled frame not an observation of its track")
    require(all(Path(p).exists() for p in bi["image"]), "a referenced review image is missing")
    print("[checks] all validations passed")


def main():
    fps = n_frames = feat = summ = None
    try:
        fps, n_frames = get_fps()
        print(f"Using FPS {fps:.3f} from {VIDEO} ({n_frames} frames)")
        feat, summ = task1(fps, n_frames)
        _, idx = task2(feat, summ)
        task3(feat, summ, idx, fps)
        checks(n_frames, feat)
    except PipelineStop as e:
        errors.append(str(e))
    except Exception as e:  # report, never overwrite silently
        errors.append(f"{type(e).__name__}: {e}")

    print("\n===== COMPLETION REPORT =====")
    print("FPS used:", fps)
    if feat is not None:
        print("Observations:", len(feat), "| Tracks:", feat['track_id'].nunique())
    if summ is not None:
        print("Tracks flagged for review:", int(summ["review_tracking"].sum()))
    print("Outputs:")
    for p in (FEATURES_OUT, SUMMARY_OUT, VALIDATION_OUT, BEHAVIOR_OUT, BEHAVIOR_INDEX_OUT, BEHAVIOR_FRAMES_DIR):
        print("  ", p, "" if Path(p).exists() else "(not written)")
    print("Errors:", errors if errors else "none")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

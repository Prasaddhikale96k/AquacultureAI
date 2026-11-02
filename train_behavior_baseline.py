"""Baseline zebrafish movement-class models with well-grouped cross-validation.

Compares majority-class, speed-only logistic regression, and a balanced Random
Forest. Folds are StratifiedGroupKFold on well_id: no well is ever in both the
training and validation side of a fold. Outputs go to runs/behavior_baseline/.
Scope: zebrafish movement classes only; nothing here applies to tilapia or
predicts fish health.
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, recall_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
FEATURES = ROOT / "dataset" / "zebrafish_behavior_prepared" / "behavior_features.csv"
OUT = ROOT / "runs" / "behavior_baseline"
META = ["feature_path", "clip_path", "normalized_label", "well_id", "group_id",
        "experiment_group", "frame_start", "frame_end"]
SPEED_ONLY = ["centroid_speed_mean", "centroid_speed_max", "keypoint_speed_mean", "keypoint_speed_max"]
N_SPLITS = 5
MIN_VAL_PER_CLASS = 20      # a fold is "sufficient" if every class has >= this many validation samples
SEEDS = range(200)
RF_SEED = 0


def build_models():
    return {
        "majority_class": DummyClassifier(strategy="most_frequent"),
        "speed_only_logreg": make_pipeline(StandardScaler(), LogisticRegression(
            class_weight="balanced", max_iter=2000)),
        "random_forest_balanced": RandomForestClassifier(
            n_estimators=300, class_weight="balanced", min_samples_leaf=3,
            random_state=RF_SEED, n_jobs=-1),
    }


def fold_coverage(y, groups, folds, classes):
    """Return (min validation count per class over folds, min #wells per class in validation, train class min)."""
    vmin, wmin, tmin = 10 ** 9, 10 ** 9, 10 ** 9
    for tr, va in folds:
        for k in classes:
            vmin = min(vmin, int((y[va] == k).sum()))
            wmin = min(wmin, len(set(groups[va][y[va] == k])))
            tmin = min(tmin, int((y[tr] == k).sum()))
    return vmin, wmin, tmin


def main():
    if not FEATURES.exists():
        raise SystemExit(f"Missing {FEATURES}; run extract_behavior_features.py first.")
    df = pd.read_csv(FEATURES)
    miss = [c for c in META if c not in df.columns]
    if miss:
        raise SystemExit(f"Feature file lacks metadata columns: {miss}")
    feat_cols = [c for c in df.columns if c not in META]
    if not np.isfinite(df[feat_cols].to_numpy()).all():
        raise SystemExit("Non-finite values in feature table; refusing to train.")
    forbidden = [c for c in feat_cols if any(t in c.lower() for t in ("well", "group", "experiment", "folder")) or c.lower().endswith("_path")]
    if forbidden:
        raise SystemExit(f"Identifier-like feature columns found: {forbidden}")

    X = df[feat_cols].to_numpy()
    y = df["normalized_label"].to_numpy()
    groups = df["well_id"].to_numpy()
    classes = sorted(set(y))
    n_wells = len(set(groups))
    limitations = []

    # ---- choose a grouped, stratified fold assignment (deterministic seed search)
    best = None
    for seed in SEEDS:
        cv = StratifiedGroupKFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)
        folds = list(cv.split(X, y, groups))
        vmin, wmin, tmin = fold_coverage(y, groups, folds, classes)
        score = (min(vmin, MIN_VAL_PER_CLASS), wmin, tmin)
        if best is None or score > best[0]:
            best = (score, seed, folds, vmin, wmin, tmin)
        if vmin >= MIN_VAL_PER_CLASS and wmin >= 1:
            break
    _, seed, folds, vmin, wmin, tmin = best
    for tr, va in folds:   # hard leakage guard
        assert not set(groups[tr]) & set(groups[va]), "well appears in train and validation"
    sufficient = vmin >= MIN_VAL_PER_CLASS
    print(f"Grouped CV: {N_SPLITS} folds over {n_wells} wells, fold seed {seed}")
    print(f"Min validation samples of any class in any fold: {vmin}; min wells per class in a validation fold: {wmin}")
    if not sufficient:
        limitations.append(f"No grouped fold assignment gave >= {MIN_VAL_PER_CLASS} validation samples of every class in "
                           f"every fold (best minimum: {vmin}); per-fold macro-F1 covers only classes present in that fold. "
                           "A random sample-level split was NOT used.")
    if wmin < 2:
        limitations.append("Some class appears in only one well within a validation fold: that fold's recall for the class "
                           "reflects a single well/larva.")

    OUT.mkdir(parents=True, exist_ok=True)
    assign = pd.DataFrame({"feature_path": df.feature_path, "well_id": groups, "label": y, "fold": -1})
    for i, (_, va) in enumerate(folds):
        assign.loc[va, "fold"] = i
    assign.to_csv(OUT / "fold_assignments.csv", index=False)

    # ---- cross-validate
    results, per_fold_rows, recall_rows, oof_all = {}, [], [], {}
    for name in build_models():
        oof = np.empty(len(y), dtype=object)
        for i, (tr, va) in enumerate(folds):
            m = build_models()[name]
            if name == "speed_only_logreg":
                cols = [feat_cols.index(c) for c in SPEED_ONLY]
                m.fit(X[tr][:, cols], y[tr])
                oof[va] = m.predict(X[va][:, cols])
            else:
                m.fit(X[tr], y[tr])
                oof[va] = m.predict(X[va])
            present = sorted(set(y[va]))
            per_fold_rows.append({
                "model": name, "fold": i, "n_val": len(va), "val_wells": len(set(groups[va])),
                "classes_present": len(present),
                "macro_f1_present_classes": f1_score(y[va], oof[va], labels=present, average="macro", zero_division=0),
                "macro_f1_all_classes": f1_score(y[va], oof[va], labels=classes, average="macro", zero_division=0)})
        oof_all[name] = oof
        cm = confusion_matrix(y, oof, labels=classes)
        pd.DataFrame(cm, index=[f"true_{k}" for k in classes], columns=[f"pred_{k}" for k in classes]) \
            .to_csv(OUT / f"confusion_matrix_{name}.csv")
        rec = recall_score(y, oof, labels=classes, average=None, zero_division=0)
        for k, r_ in zip(classes, rec):
            recall_rows.append({"model": name, "class": k, "recall": r_, "n": int((y == k).sum())})
        results[name] = {
            "pooled_macro_f1": f1_score(y, oof, labels=classes, average="macro", zero_division=0),
            "pooled_accuracy": float((y == oof).mean()),
            "per_class_recall": {k: float(r_) for k, r_ in zip(classes, rec)}}
    pf = pd.DataFrame(per_fold_rows)
    pf.to_csv(OUT / "per_fold_metrics.csv", index=False)
    pd.DataFrame(recall_rows).to_csv(OUT / "per_class_recall.csv", index=False)
    pd.DataFrame({"feature_path": df.feature_path, "well_id": groups, "true": y,
                  **{f"pred_{n}": v for n, v in oof_all.items()}}).to_csv(OUT / "oof_predictions.csv", index=False)
    for n in results:
        s = pf[pf.model == n]
        results[n]["fold_macro_f1_present_mean"] = float(s.macro_f1_present_classes.mean())
        results[n]["fold_macro_f1_present_sd"] = float(s.macro_f1_present_classes.std())

    # ---- final RF on all wells (for later use; NOT evaluated on held-out data)
    final = build_models()["random_forest_balanced"].fit(X, y)
    imp = pd.Series(final.feature_importances_, index=feat_cols).sort_values(ascending=False)
    imp.rename("importance").to_csv(OUT / "rf_feature_importance.csv")
    joblib.dump({"model": final, "feature_columns": feat_cols, "classes": classes,
                 "note": "Zebrafish 60-frame keypoint movement classes only. Trained on all wells; "
                         "use CV metrics for performance. Speeds are coordinate units/frame (units/FPS unverified)."},
                OUT / "random_forest_baseline.joblib")

    # ---- misclassifications for the report
    cm_rf = pd.read_csv(OUT / "confusion_matrix_random_forest_balanced.csv", index_col=0)
    summary = {
        "n_samples": int(len(y)), "n_wells": int(n_wells), "n_features": len(feat_cols), "classes": classes,
        "cv": {"splitter": "StratifiedGroupKFold", "groups": "well_id", "n_splits": N_SPLITS, "seed": int(seed),
               "min_val_samples_any_class_any_fold": int(vmin), "min_val_wells_any_class_any_fold": int(wmin),
               "coverage_sufficient": bool(sufficient)},
        "models": results, "limitations": limitations}
    (OUT / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== Pooled out-of-fold results ===")
    for n, r_ in results.items():
        print(f"{n}: macro-F1 {r_['pooled_macro_f1']:.3f}  accuracy {r_['pooled_accuracy']:.3f}  "
              f"fold macro-F1 {r_['fold_macro_f1_present_mean']:.3f} +/- {r_['fold_macro_f1_present_sd']:.3f}")
        print("   recall: " + ", ".join(f"{k} {v:.2f}" for k, v in r_["per_class_recall"].items()))
    print("\nRandom Forest confusion matrix (rows = true):")
    print(cm_rf.to_string())
    print("\nPer-fold (RF):")
    print(pf[pf.model == "random_forest_balanced"].round(3).to_string(index=False))
    print("\nTop features:", ", ".join(f"{k} {v:.3f}" for k, v in imp.head(6).items()))
    print("\nLimitations:" if limitations else "\nLimitations: none flagged by coverage checks")
    for l in limitations:
        print(" -", l)
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    main()

import pandas as pd
import numpy as np
import joblib
import matplotlib.pyplot as plt

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay,
    accuracy_score,
)

DATA_FILE = "behavior_review_provisional.xlsx"

df = pd.read_excel(DATA_FILE)

features = [
    "observations",
    "duration_sec",
    "mean_speed_px_sec",
    "median_speed_px_sec",
    "speed_variation",
    "mean_confidence",
    "tracking_jumps",
]

X = df[features].replace([np.inf, -np.inf], np.nan)
y = df["behavior_label"].astype(str).str.strip()

valid = X.notna().all(axis=1) & y.ne("")
X, y = X.loc[valid], y.loc[valid]

if y.nunique() < 2 or y.value_counts().min() < 2:
    raise ValueError("Need at least 2 labels and 2 samples per class.")

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y
)

model = RandomForestClassifier(
    n_estimators=200,
    random_state=42,
    class_weight="balanced",
)
model.fit(X_train, y_train)

predictions = model.predict(X_test)

print("Test tracks:", len(X_test))
print("Accuracy against PROVISIONAL labels:",
      round(accuracy_score(y_test, predictions), 3))
print("\nClassification report:")
print(classification_report(y_test, predictions, zero_division=0))

labels = sorted(y.unique())
cm = confusion_matrix(y_test, predictions, labels=labels)
ConfusionMatrixDisplay(
    confusion_matrix=cm, display_labels=labels
).plot(cmap="Blues", values_format="d")

plt.tight_layout()
plt.savefig("behavior_confusion_matrix.png", dpi=160)
plt.close()

joblib.dump(
    {"model": model, "features": features},
    "behavior_random_forest.joblib",
)

results = X_test.copy()
results["actual_provisional_label"] = y_test
results["predicted_label"] = predictions
results.to_csv("behavior_test_predictions.csv", index=True)

print("\nSaved:")
print("- behavior_random_forest.joblib")
print("- behavior_confusion_matrix.png")
print("- behavior_test_predictions.csv")
print("\nWARNING: Labels are heuristic, not visually verified.")
print("Metrics measure agreement with those provisional labels,")
print("not real-world fish-behavior accuracy.")
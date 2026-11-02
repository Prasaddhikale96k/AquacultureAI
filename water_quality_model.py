import pandas as pd
import json

INPUT = r"dataset\Tilapia RAS Dataset\Documentation\meta_tilapia_set.csv"
OUTPUT = "water_quality_analysis.csv"
CONFIG = "water_quality_config.json"

# Provisional screening thresholds: verify for your tank and fish stage.
DEFAULT_THRESHOLDS = {
    "temperature_C": {"min": 25.0, "max": 32.0},
    "pH": {"min": 6.5, "max": 8.5},
    "DO_mgL": {"min": 5.0, "max": None},
    "turbidity_NTU": {"min": None, "max": 15.0},
}

try:
    with open(CONFIG, "r", encoding="utf-8") as f:
        thresholds = json.load(f)
except FileNotFoundError:
    thresholds = DEFAULT_THRESHOLDS
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(thresholds, f, indent=4)


def analyze_reading(reading):
    alerts = {}

    for parameter, limits in thresholds.items():
        value = reading.get(parameter)

        if value is None or pd.isna(value):
            alerts[parameter] = "MISSING READING"
        elif limits.get("min") is not None and value < limits["min"]:
            alerts[parameter] = "LOW"
        elif limits.get("max") is not None and value > limits["max"]:
            alerts[parameter] = "HIGH"
        else:
            alerts[parameter] = "NO RULE TRIGGERED"

    return alerts


def summarize_alerts(alerts):
    triggered = [
        f"{parameter}: {status}"
        for parameter, status in alerts.items()
        if status not in ("NO RULE TRIGGERED",)
    ]
    return "; ".join(triggered) if triggered else "No rule-based alert"


# Analyze the historical dataset.
df = pd.read_csv(INPUT)

parameters = list(thresholds.keys())
for parameter in parameters:
    df[parameter] = pd.to_numeric(df[parameter], errors="coerce")

for parameter in parameters:
    df[f"{parameter}_status"] = df.apply(
        lambda row: analyze_reading(row.to_dict())[parameter], axis=1
    )

df["water_quality_alerts"] = df.apply(
    lambda row: summarize_alerts(analyze_reading(row.to_dict())), axis=1
)

df["status"] = df["water_quality_alerts"].apply(
    lambda value: "REVIEW REQUIRED"
    if value != "No rule-based alert"
    else "NO RULE TRIGGERED"
)

df.to_csv(OUTPUT, index=False)

print("Historical analysis completed!")
print("Records analyzed:", len(df))
print("\nOverall status:")
print(df["status"].value_counts().to_string())

print("\nParameter alert counts:")
for parameter in parameters:
    print(f"{parameter}:")
    print(df[f"{parameter}_status"].value_counts().to_string())

print("\nSaved:", OUTPUT)

# Example of analyzing one new reading (not a live sensor reading).
example = {
    "temperature_C": 29.5,
    "pH": 7.8,
    "DO_mgL": 5.2,
    "turbidity_NTU": 8.0,
}
print("\nExample reading:")
print(analyze_reading(example))
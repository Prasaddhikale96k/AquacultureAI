import pandas as pd

source = "fish_behavior_analysis.csv"
output = "behavior_labels.csv"

df = pd.read_csv(source)

# Keep track features and add a blank column for human-reviewed labels.
df["behavior_label"] = ""

df["review_notes"] = ""

df.to_csv(output, index=False)

print("Labeling template created:", output)
print("Tracks available:", len(df))
print("\nOpen the CSV in Excel and fill behavior_label")
print("only after reviewing the corresponding video.")
print("\nSuggested labels:")
print("normal_activity")
print("low_activity")
print("surface_gathering")
print("irregular_movement")
print("\nDo not label a behavior if the video does not provide")
print("enough visual evidence.")
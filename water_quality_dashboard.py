import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("water_quality_analysis.csv")

parameters = [
    ("temperature_C", "Temperature (°C)"),
    ("pH", "pH"),
    ("DO_mgL", "Dissolved oxygen (mg/L)"),
    ("turbidity_NTU", "Turbidity (NTU)")
]

fig, axes = plt.subplots(2, 2, figsize=(12, 8))

for ax, (column, label) in zip(axes.flat, parameters):
    ax.plot(range(1, len(df) + 1), df[column], marker="o")
    ax.set_title(label)
    ax.set_xlabel("Metadata record")
    ax.set_ylabel(label)
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("water_quality_dashboard.png", dpi=150)
print("Dashboard saved: water_quality_dashboard.png")
plt.savefig("water_quality_dashboard.png", dpi=150)
from pathlib import Path
import random
import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image

ROOT = Path(__file__).parent

DATASET = ROOT / "dataset" / "Tilapia RAS Dataset"
FRAMES = DATASET / "Frames" / "Original"
CSV_PATH = DATASET / "Documentation" / "meta_tilapia_set.csv"

# Load water-quality metadata
df = pd.read_csv(CSV_PATH)

# Find actual fish images
images = list(FRAMES.rglob("images/*.jpg"))
random.seed(42)
samples = random.sample(images, min(15, len(images)))

fig, axes = plt.subplots(5, 3, figsize=(16, 10))
axes = axes.flatten()

for ax, image_path in zip(axes, samples):
    image = Image.open(image_path).convert("RGB")
    ax.imshow(image)

    # Folder name identifies the video group
    clip_id = image_path.parent.parent.name

    # Match the image's video group to metadata
    match = df[
        df["clip_id"].astype(str).str.contains(
            clip_id, regex=False, case=False
        )
    ]

    if not match.empty:
        row = match.iloc[0]

        details = (
            f"Temperature: {row['temperature_C']} °C\n"
            f"pH: {row['pH']}\n"
            f"DO: {row['DO_mgL']} mg/L\n"
            f"Turbidity: {row['turbidity_NTU']} NTU\n"
            f"Fish count: {row['fish_count_est']}"
        )
    else:
        details = f"Metadata not matched\nGroup: {clip_id}"

    ax.set_title(details, fontsize=10)
    ax.axis("off")

# Hide unused panels
for ax in axes[len(samples):]:
    ax.axis("off")

plt.tight_layout()
plt.show()
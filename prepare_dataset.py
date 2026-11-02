import json
import random
import shutil
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent
SOURCE = ROOT / "dataset" / "Tilapia RAS Dataset" / "Frames" / "Original"
DEST = ROOT / "dataset" / "tilapia_yolo"
random.seed(42)

groups = defaultdict(list)

for ann in SOURCE.rglob("*.json"):
    data = json.loads(ann.read_text(encoding="utf-8"))
    image = ann.parent.parent / "images" / data["imagePath"]

    if not image.exists() or not data.get("shapes"):
        continue

    # Example: GX030013_00014.jpg -> GX030013
    video_id = image.stem.rsplit("_", 1)[0]
    groups[video_id].append((image, data))

video_ids = sorted(groups)
random.shuffle(video_ids)

if len(video_ids) < 3:
    raise RuntimeError(
        f"Only {len(video_ids)} video IDs found; "
        "need at least 3 independent videos for train/val/test."
    )

n = len(video_ids)
n_train = max(1, round(n * 0.70))
n_val = max(1, round(n * 0.15))

if n_train + n_val >= n:
    n_train, n_val = n - 2, 1

splits = {
    "train": video_ids[:n_train],
    "val": video_ids[n_train:n_train + n_val],
    "test": video_ids[n_train + n_val:],
}

if DEST.exists():
    shutil.rmtree(DEST)

counts = {}

for split, ids in splits.items():
    count = 0

    for vid in ids:
        for image, data in groups[vid]:
            name = f"{vid}_{image.name}"

            image_dir = DEST / "images" / split
            label_dir = DEST / "labels" / split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)

            shutil.copy2(image, image_dir / name)

            lines = []
            for shape in data["shapes"]:
                points = shape.get("points", [])
                if len(points) < 3:
                    continue

                coords = []
                for x, y in points:
                    coords.extend([
                        max(0.0, min(1.0, x / data["imageWidth"])),
                        max(0.0, min(1.0, y / data["imageHeight"])),
                    ])

                lines.append(
                    "0 " + " ".join(f"{v:.6f}" for v in coords)
                )

            (label_dir / f"{Path(name).stem}.txt").write_text(
                "\n".join(lines), encoding="utf-8"
            )
            count += 1

    counts[split] = count

yaml = DEST / "data.yaml"
yaml.write_text(
    f"path: {DEST.as_posix()}\n"
    "train: images/train\n"
    "val: images/val\n"
    "test: images/test\n"
    "names:\n"
    "  0: tilapia\n",
    encoding="utf-8",
)

print("Video IDs:", len(video_ids))
print("Video split:", {k: len(v) for k, v in splits.items()})
print("Image split:", counts)
print("Config:", yaml)
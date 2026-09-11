"""Audit all model files and datasets."""
from pathlib import Path
import json

# Check all ONNX files
print("=== ONNX FILES ===")
for p in Path(".").rglob("*.onnx"):
    if "node_modules" not in str(p) and ".venv" not in str(p):
        print(f"  {p}  ({p.stat().st_size / 1024 / 1024:.1f} MB)")

# Check classes.json
cj = Path("dataset/annotation/classes.json")
if cj.exists():
    print("\n=== classes.json ===")
    classes = json.loads(cj.read_text())
    for k, v in classes.items():
        print(f"  {v}: {k}")

# Check data.yaml
for dy in Path("dataset").rglob("data.yaml"):
    print(f"\n=== {dy} ===")
    print(dy.read_text())

# Check sub8k
sub8k = Path("dataset/roboflow/sub8k")
if sub8k.exists():
    train_imgs = list((sub8k / "train" / "images").glob("*.jpg")) if (sub8k / "train" / "images").exists() else []
    val_imgs = list((sub8k / "val" / "images").glob("*.jpg")) if (sub8k / "val" / "images").exists() else []
    print(f"\n=== sub8k dataset ===")
    print(f"  train: {len(train_imgs)} images")
    print(f"  val: {len(val_imgs)} images")

# Check raw dataset labels
raw = Path("dataset/raw")
if raw.exists():
    print("\n=== raw dataset ===")
    for d in sorted(raw.iterdir()):
        if d.is_dir():
            frames = list(d.glob("*.jpg"))
            print(f"  {d.name}: {len(frames)} frames")

# Check for any trained models
print("\n=== SEARCHING FOR TRAINED MODELS ===")
for name in ["best.onnx", "best.pt", "last.pt", "last.onnx"]:
    for p in Path(".").rglob(name):
        if "node_modules" not in str(p) and ".venv" not in str(p):
            print(f"  FOUND: {p} ({p.stat().st_size / 1024 / 1024:.1f} MB)")

# Check yolov8n.names
names = Path("models/detection/yolov8n.names")
if names.exists():
    classes = names.read_text().strip().splitlines()
    print(f"\n=== yolov8n.names ({len(classes)} classes) ===")
    for i, c in enumerate(classes):
        print(f"  [{i:3d}] {c}")

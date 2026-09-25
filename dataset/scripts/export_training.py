"""Export the annotated split as a YOLO ``data.yaml`` for training (Phase 4C).

Validates the session-aware split built by ``prepare_split.py`` (labels
present, class ids in range, no session or exact-image leakage, provable
recording-session directories) and writes a ``data.yaml`` the ultralytics
trainer consumes directly.

    .\\.venv\\Scripts\\python.exe dataset\\scripts\\export_training.py --root dataset
    # -> dataset/training/data.yaml

Exit code 0 = written, 2 = split is not trainable (see messages).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

from annotation.annotator import load_classes  # noqa: E402
from training_tool import DATA_YAML_NAME, TRAINING_DIR_NAME, make_data_yaml  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Write a validated YOLO data.yaml from the annotated split"
    )
    parser.add_argument(
        "--root",
        default=str(DATASET_DIR),
        help="dataset root holding the train/val/test split (default: dataset/)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"where to write {DATA_YAML_NAME} (default: <root>/{TRAINING_DIR_NAME}/{DATA_YAML_NAME})",
    )
    parser.add_argument("--classes", default=None, help="path to classes.json")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / "train" / "images").is_dir():
        parser.error(f"split not found - run prepare_split.py first (missing: {root / 'train' / 'images'})")

    try:
        summary = make_data_yaml(root, classes=load_classes(args.classes), output=args.output)
    except ValueError as exc:
        parser.exit(2, f"Export failed: {exc}\n")

    print(f"data.yaml written: {summary['yaml']}")
    print(f"classes: {', '.join(summary['classes'])} ({len(summary['classes'])})")
    print(f"split layout: {summary['layout']}")
    for split in ("train", "val", "test"):
        count = summary["images"].get(split, 0)
        if count:
            per_class = ", ".join(
                f"{name}={summary['histogram'][split][i]}" for i, name in enumerate(summary["classes"])
            )
            print(f"  {split:5s} images={count:4d}  boxes/class: {per_class}")
    for split, names in summary["zero_classes"].items():
        if names and summary["images"].get(split):
            print(f"  WARNING: {split} has 0 boxes for: {', '.join(names)}")

    print(
        "\nNext steps (train on the machine that runs ultralytics; see "
        "dataset/requirements-train.txt):"
    )
    print(f'  yolo train data={summary["yaml"]} model=yolov8n.pt epochs=200 imgsz=640')
    print("  yolo export model=runs/detect/train/weights/best.pt format=onnx")
    print("  # then install the export for the backend runtime:")
    print(
        "  .\\.venv\\Scripts\\python.exe dataset\\scripts\\install_detection_model.py "
        "--onnx runs/detect/train/weights/best.onnx"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
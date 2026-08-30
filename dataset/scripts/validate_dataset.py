"""Validate the BAS dataset + train/val/test split (Phase 4B).

Checks, per image/label pair:

- the image file exists and the label file exists beside it
- every label is well-formed YOLO (``class cx cy w h``, 5 fields)
- class ids are in range for ``annotation/classes.json``
- coordinates are in [0, 1] and width/height are positive
- the box stays inside the image
- no label is orphaned (label without its image, image without its label)

Cross-split check:

- the same recording session never appears in more than one of train/val/test

    .\\.venv\\Scripts\\python.exe dataset\\scripts\\validate_dataset.py
    .\\.venv\\Scripts\\python.exe dataset\\scripts\\validate_dataset.py --root dataset

Exit code 0 = OK, 1 = errors found. Warnings (unannotated images) are fine.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

from annotation.annotator import load_classes, validate_dataset  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Validate the BAS dataset and its split")
    parser.add_argument("--root", default=str(DATASET_DIR), help="dataset root (raw/, annotations/, train/, ...)")
    parser.add_argument("--classes", default=None, help="path to classes.json")
    args = parser.parse_args(argv)

    classes = load_classes(args.classes)
    root = Path(args.root).resolve()
    report = validate_dataset(root, classes=classes)

    print(f"Dataset: {root}")
    print(f"Classes: {classes} ({len(classes)})")
    raw = report.stats.get("raw")
    if raw:
        print(
            f"Raw:            images={raw.get('images', 0):4d}  "
            f"annotated={raw['annotated']}  "
            f"unannotated={raw['images'] - raw['annotated']}"
        )
    for split in ("train", "val", "test"):
        info = report.stats.get(split)
        if info:
            print(
                f"{split:6s} split: images={info['images']:4d}   "
                f"labels={info['labels']:4d}   missing={info['missing_labels']:4d}"
            )
    print(f"Session leakage: {len(find_session_leakage_names(report))} session(s) span multiple splits")
    for line in find_session_leakage_names(report):
        print(f"  {line}")

    if report.warnings:
        print(f"\nWarnings ({len(report.warnings)}):")
        for line in report.warnings[:10]:
            print(f"  ! {line}")
        if len(report.warnings) > 10:
            print(f"  ... and {len(report.warnings) - 10} more")
    if report.errors:
        print(f"\nErrors ({len(report.errors)}):")
        for line in report.errors[:25]:
            print(f"  x {line}")
        if len(report.errors) > 25:
            print(f"  ... and {len(report.errors) - 25} more")
        print("\nRESULT: FAILED")
        return 1

    print("\nRESULT: OK - dataset is clean")
    return 0


def find_session_leakage_names(report) -> list[str]:
    return [line for line in report.errors if "more than one split" in line]


if __name__ == "__main__":
    sys.exit(main())
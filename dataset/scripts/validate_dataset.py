"""Validate the BAS dataset + train/val/test split (Phase 4B).

Checks, per image/label pair:

- the image file exists and the label file exists beside it
- every label is well-formed YOLO (``class cx cy w h``, 5 fields)
- class ids are in range for ``annotation/classes.json``
- coordinates are in [0, 1] and width/height are positive
- the box stays inside the image
- no label is orphaned (label without its image, image without its label)

Cross-split checks:

- a named recording session never appears in more than one of train/val/test
- byte-identical images are not shared across splits
- flat layouts are reported as unverifiable session isolation

    .\\.venv\\Scripts\\python.exe dataset\\scripts\\validate_dataset.py
    .\\.venv\\Scripts\\python.exe dataset\\scripts\\validate_dataset.py --root dataset
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

from annotation.annotator import load_classes, validate_dataset  # noqa: E402
from roboflow_tool import load_roboflow_classes  # noqa: E402


def _load_class_list(path: str | None, parser: argparse.ArgumentParser) -> list[str]:
    if path is None:
        return load_classes()
    classes_path = Path(path)
    if not classes_path.is_file():
        parser.error(f"classes file not found: {classes_path}")
    if classes_path.suffix.lower() in {".yaml", ".yml"}:
        return load_roboflow_classes(classes_path)
    return load_classes(classes_path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Validate the BAS dataset and its split")
    parser.add_argument(
        "--root", default=str(DATASET_DIR), help="dataset root (raw/, annotations/, train/, ...)"
    )
    parser.add_argument(
        "--classes",
        default=None,
        help="classes.json or data.yaml; defaults to annotation/classes.json",
    )
    parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="report byte-identical cross-split images as warnings instead of errors",
    )
    args = parser.parse_args(argv)

    classes = _load_class_list(args.classes, parser)
    root = Path(args.root).resolve()
    report = validate_dataset(root, classes=classes, allow_duplicates=args.allow_duplicates)

    print(f"Dataset: {root}")
    print(f"Classes: {classes} ({len(classes)})")
    print(f"Split layout: {report.stats.get('layout', 'empty')}")
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
            histogram = info.get("histogram", [])
            per_class = ", ".join(
                f"{name}={histogram[i]}" if i < len(histogram) else f"{name}=?"
                for i, name in enumerate(classes)
            )
            print(
                f"{split:6s} split: images={info['images']:4d}   "
                f"labels={info['labels']:4d}   missing={info['missing_labels']:4d}   "
                f"boxes/class: {per_class}"
            )
    print(f"Session leakage: {len(find_session_leakage_names(report))} session(s) span multiple splits")
    for line in find_session_leakage_names(report):
        print(f"  {line}")
    duplicates = report.stats.get("duplicates", {})
    print(
        "Duplicate images: "
        f"cross-split groups={duplicates.get('cross_split_groups', 0)}  "
        f"within-split groups={duplicates.get('within_split_groups', 0)}"
    )
    for group in duplicates.get("cross_split", []):
        print(f"  {' == '.join(group)}")

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
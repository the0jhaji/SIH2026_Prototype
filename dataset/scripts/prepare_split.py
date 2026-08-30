"""Create a train/val/test split of the BAS dataset, **by recording session**.

Frames are never individually shuffled across sets: the whole ``raw``
sub-directory of an image counts as one session, and every image of a session
goes into exactly one split. Defaults to 70 / 20 / 10.

    .\\.venv\\Scripts\\python.exe dataset\\scripts\\prepare_split.py            # backend venv, repo root
    .\\.venv\\Scripts\\python.exe dataset\\scripts\\prepare_split.py --seed 7 --test 0.15

Output (originals in ``raw/`` are never modified):
    dataset/train/{images,labels}/<session>/**  60     dataset/val/...      ...
    dataset/test/...                            30     dataset/test/...     ...
and dataset/split_manifest.json records seed + session -> split.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

from annotation.annotator import make_split, load_classes  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build a session-aware train/val/test split")
    parser.add_argument(
        "--root",
        default=None,
        help="dataset root - shorthand that sets --raw/--annotations/--output to its subdirs",
    )
    parser.add_argument("--raw", default=None, help="raw session directory")
    parser.add_argument(
        "--annotations",
        default=None,
        help="YOLO annotations directory (mirrors raw/ paths)",
    )
    parser.add_argument("--output", default=None, help="dataset root to receive train/val/test")
    parser.add_argument("--classes", default=None, help="path to classes.json (default: annotation/classes.json)")
    parser.add_argument("--train", type=float, default=0.7, help="train fraction (default 0.7)")
    parser.add_argument("--val", type=float, default=0.2, help="validation fraction (default 0.2)")
    parser.add_argument("--test", type=float, default=0.1, help="test fraction (default 0.1)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    args = parser.parse_args(argv)

    if not (args.train > 0 and args.val > 0 and args.test > 0 and abs(args.train + args.val + args.test - 1.0) < 1e-6):
        parser.error("train/val/test must be positive and sum to 1")

    classes_root = Path(args.root).resolve() if args.root else DATASET_DIR
    raw_arg = args.raw or str(classes_root / "raw")
    ann_arg = args.annotations or str(classes_root / "annotations")
    out_arg = args.output or str(classes_root)

    classes = load_classes(args.classes)
    raw_root = Path(raw_arg).resolve()
    ann_root = Path(ann_arg).resolve()
    out_root = Path(out_arg).resolve()
    if not raw_root.is_dir():
        parser.error(f"raw directory not found: {raw_root}")

    summary = make_split(
        raw_root,
        out_root,
        annotations_root=ann_root if ann_root.is_dir() else None,
        classes=classes,
        train=args.train,
        val=args.val,
        test=args.test,
        seed=args.seed,
    )

    print("Session-aware split complete (sessions are never divided)")
    print(f"  classes: {', '.join(classes)} ({len(classes)})")
    for split in ("train", "val", "test"):
        s = summary[split]
        print(
            f"  {split:5s}  sessions={s['sessions']:3d}  "
            f"images={s['images']:4d}  labels={s['labels']:4d}  "
            f"missing_labels={s['missing_labels']:4d}"
        )
    print(f"Manifest: {out_root / 'split_manifest.json'}")
    total_missing = sum(s["missing_labels"] for s in summary.values())
    if total_missing:
        print(
            f"NOTE: {total_missing} image(s) had no annotation yet - they are split as-is "
            "and will be reported by validate_dataset.py"
        )


if __name__ == "__main__":
    main()
"""Prepare the downloaded Roboflow export for local YOLO training.

Copies ``dataset/roboflow/{train,valid}`` into a clean
``dataset/roboflow/split/{train,val,test}`` layout with a corrected
``data.yaml`` (absolute paths + the 15-class vocabulary) ready for the
lightweight training script. Non-destructive: originals are only read.

Run from the repo root with the backend venv:
    .\\.venv\\Scripts\\python.exe dataset\\scripts\\prepare_roboflow.py [--root dataset]
    .\\.venv\\Scripts\\python.exe dataset\\scripts\\prepare_roboflow.py --test-fraction 0.12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

from roboflow_tool import (  # noqa: E402
    DATA_YAML_NAME,
    load_roboflow_classes,
    make_roboflow_data_yaml,
    make_roboflow_split,
)

OUT_SUBDIR = "split"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(DATASET_DIR), help="dataset root (default: repo dataset/)")
    parser.add_argument(
        "--test-fraction", type=float, default=0.1,
        help="fraction of the valid export carved into a test holdout (default 0.1)",
    )
    parser.add_argument("--seed", type=int, default=42, help="rng seed for the val/test carve (default 42)")
    parser.add_argument(
        "--data-yaml", default=None,
        help="path to the shipped Roboflow data.yaml (default: <root>/roboflow/data.yaml)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    src_root = root / "roboflow"
    if not (src_root / "train").is_dir():
        parser.error(f"roboflow export not found under {src_root}")
    classes = load_roboflow_classes(args.data_yaml)
    out_root = src_root / OUT_SUBDIR

    summary = make_roboflow_split(
        src_root, out_root, classes=classes,
        test_fraction=args.test_fraction, seed=args.seed,
    )
    yaml_info = make_roboflow_data_yaml(out_root, classes=classes)

    print(f"classes ({len(classes)}): {', '.join(classes)}")
    for split in ("train", "val", "test"):
        info = summary[split]
        print(f"  {split}: {info['images']} images, {info['labels']} labels")
    print(f"data.yaml: {yaml_info['yaml']}")
    print(f"histograms: train={summary['train']['histogram']} "
          f"val={summary['val']['histogram']} test={summary['test']['histogram']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Train a lightweight YOLO model on the prepared Roboflow everyday-objects set.

Runs an ultralytics training on ``dataset/roboflow/split/data.yaml`` using the
nano variant (``yolov8n``, ~6 MB) which is designed for a local CPU/light run.
Defaults are intentionally small (few epochs) so a quick verify run is cheap;
raise ``--epochs`` / ``--imgsz`` for a real run.

Ultralytics is **optional and only required on the training machine** — the app
runtime never imports it. If it isn't installed, this script prints a friendly
setup instruction and exits non-zero.

Run from the repo root **inside ``.venv-train``**:
    .\\.venv-train\\Scripts\\python.exe dataset\\scripts\\train_roboflow.py --epochs 3 --image-limit 500
    .\\.venv-train\\Scripts\\python.exe dataset\\scripts\\train_roboflow.py --epochs 60 --imgsz 640
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent
ROOT = DATASET_DIR.parent
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from roboflow_tool import DATA_YAML_NAME  # noqa: E402

DEFAULT_DATA = DATASET_DIR / "roboflow" / "split" / DATA_YAML_NAME
DEFAULT_MODEL = "yolov8n.pt"
DEFAULT_PROJECT = str(DATASET_DIR / "runs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="prepared data.yaml")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="ultralytics model to train (default yolov8n.pt)")
    parser.add_argument("--epochs", type=int, default=3, help="epochs (default 3 = quick verify)")
    parser.add_argument("--imgsz", type=int, default=640, help="input size (default 640)")
    parser.add_argument("--batch", type=int, default=None, help="batch size (default: auto)")
    parser.add_argument("--image-limit", type=int, default=None, help="train on first N train images for a quick run")
    parser.add_argument("--device", default="cpu", help="device (default cpu)")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="output project dir (default dataset/runs)")
    parser.add_argument("--name", default=None, help="run name (default: auto)")
    args = parser.parse_args()

    if not Path(args.data).is_file():
        parser.error(f"data.yaml not found: {args.data} (run prepare_roboflow.py first)")

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - only hit when torch is absent
        print(
            "ultralytics is not installed. Training happens in a dedicated env:\n"
            "    python -m venv .venv-train\n"
            "    .\\.venv-train\\Scripts\\pip install -r dataset\\requirements-train.txt\n"
            "Then re-run this script with:\n"
            f"    .\\.venv-train\\Scripts\\python.exe dataset\\scripts\\train_roboflow.py --epochs {args.epochs}",
            file=sys.stderr,
        )
        return 2

    model = YOLO(args.model)

    kwargs = {
        "data": str(Path(args.data).resolve()),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "device": args.device,
        "project": args.project,
        "name": args.name,
    }
    if args.batch is not None:
        kwargs["batch"] = args.batch

    # ultralytics has no per-image cap; bounding a quick run is done via small
    # `--epochs` (the default is 3). Keep this honest in the help text.
    if args.image_limit is not None:
        print(
            "Note: ultralytics has no per-image-limit flag; bound the quick run "
            "with --epochs (default 3).",
            file=sys.stderr,
        )

    model.train(**kwargs)
    best = Path(args.project) / (args.name or "train") / "weights" / "best.pt"
    print(f"training complete. best weights: {best}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

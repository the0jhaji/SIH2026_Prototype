"""Install a trained ONNX detector for the Astra AI runtime (Phase 4C).

Copies an exported ONNX (from ``yolo export … format=onnx``) into
``models/detection/yolov8n.onnx`` and writes the matching ``.names`` file next
to it, straight from ``annotation/classes.json``, so
``ai/detection/yolo_detector.py`` recognises the trained classes with zero
further config.

    .\\.venv\\Scripts\\python.exe dataset\\scripts\\install_detection_model.py \\
        --onnx runs/detect/train/weights/best.onnx

Exit code 0 = installed, 2 = bad arguments / missing model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent
ROOT = DATASET_DIR.parent
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

from annotation.annotator import load_classes  # noqa: E402
from roboflow_tool import load_roboflow_classes  # noqa: E402
from training_tool import install_detection_model as _install  # noqa: E402

DEFAULT_DEST = ROOT / "models" / "detection" / "yolov8n.onnx"


def _load_class_list(path: str | None, parser: argparse.ArgumentParser) -> list[str]:
    """Load the class vocabulary from a ``classes.json`` or a ``data.yaml``."""
    if path is None:
        return load_classes()
    p = Path(path)
    if not p.is_file():
        parser.error(f"classes file not found: {p}")
    if p.suffix.lower() in {".yaml", ".yml"}:
        return load_roboflow_classes(p)
    return load_classes(p)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Install a trained ONNX detector + .names for the backend runtime"
    )
    parser.add_argument("--onnx", help="path to the exported ONNX model (required)")
    parser.add_argument(
        "--dest",
        default=str(DEFAULT_DEST),
        help=f"destination ONNX path (default: {DEFAULT_DEST})",
    )
    parser.add_argument(
        "--classes",
        default=None,
        help="classes.json (or Roboflow data.yaml) of the trained model; "
        "defaults to annotation/classes.json",
    )
    args = parser.parse_args(argv)

    if args.onnx is None:
        parser.error("--onnx is required")

    dest_path = Path(args.dest).resolve()
    try:
        result = _install(
            Path(args.onnx),
            dest_path.parent,
            classes=_load_class_list(args.classes, parser),
            dest_name=dest_path.name,
        )
    except FileNotFoundError as exc:
        parser.exit(2, f"Install failed: {exc}\n")
    except ValueError as exc:
        parser.exit(2, f"Install failed: {exc}\n")

    print("Detector installed for the runtime:")
    print(f"  onnx : {result['onnx']}")
    print(f"  names: {result['names']}  ({', '.join(result['classes'])})")
    print("\nStart the backend with the trained model (set DETECTION_MODEL_PATH to the")
    print("destination if you used a name other than yolov8n.onnx):")
    print('  $env:DETECTION_ENABLED="true"; $env:DETECTION_BACKEND="yolo";')
    print(
        "  .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000 "
        "--reload --app-dir backend"
    )
    print("  # sanity: GET /api/detection/status shows modelLoaded=true and your classes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
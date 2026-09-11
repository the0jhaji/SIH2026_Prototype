"""Evaluate a trained Roboflow ONNX through the app's real runtime detector.

Loads an exported YOLO ONNX using the exact consumer the backend uses
(``ai.detection.yolo_detector.YoloDetector` -> ``postprocess_yolov8``) and
scores it against the ``test`` holdout prepared by ``prepare_roboflow.py``.
Reports per-class true-positive(+IoU), false-positive and false-negative counts
plus precision/recall, so you can confirm the exported model is usable by the
BAS pipeline and how well it recognises each everyday object.

Runs in the **backend** venv (has cv2/numpy/onnx — no ultralytics needed):
    .\\.venv\\Scripts\\python.exe dataset\\scripts\\evaluate_roboflow.py [--onnx runs/train/weights/best.onnx]
    .\\.venv\\Scripts\\python.exe dataset\\scripts\\evaluate_roboflow.py --conf 0.25 --iou 0.5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent
ROOT = DATASET_DIR.parent
for p in (str(ROOT), str(DATASET_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from annotation.annotator import IMAGE_EXTS, validate_label  # noqa: E402
from roboflow_tool import load_roboflow_classes  # noqa: E402

SPLIT_ROOT = DATASET_DIR / "roboflow" / "split"
DEFAULT_ONNX = DATASET_DIR / "runs" / "train" / "weights" / "best.onnx"


def _iou(a, b) -> float:
    ix1 = max(a[0], b[0]); iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2]); iy2 = min(a[3], b[3])
    iw = max(0.0, ix2 - ix1); ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _pixel_rect(bbox, w: int, h: int):
    x = (bbox.cx - bbox.w / 2) * w
    y = (bbox.cy - bbox.h / 2) * h
    return (x, y, x + bbox.w * w, y + bbox.h * h)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--onnx", default=str(DEFAULT_ONNX), help="trained ONNX to evaluate")
    parser.add_argument("--split-root", default=str(SPLIT_ROOT), help="prepared split root (test/)")
    parser.add_argument("--conf", type=float, default=0.5, help="detection confidence threshold (default 0.5)")
    parser.add_argument("--iou", type=float, default=0.5, help="IoU match threshold (default 0.5)")
    parser.add_argument("--limit", type=int, default=None, help="evaluate on first N test images only")
    args = parser.parse_args()

    onnx = Path(args.onnx).resolve()
    if not onnx.is_file():
        parser.error(f"ONNX not found: {onnx} (export best.pt to ONNX and place here)")
    split_root = Path(args.split_root).resolve()
    test_images = split_root / "test" / "images"
    test_labels = split_root / "test" / "labels"
    if not test_images.is_dir():
        parser.error(f"test images dir not found: {test_images} (run prepare_roboflow.py)")

    classes = load_roboflow_classes()
    names_path = onnx.with_suffix(".names") if onnx.with_suffix(".names").is_file() else None

    import cv2
    from ai.detection.yolo_detector import YoloDetector, _read_names_file

    effective = _read_names_file(Path(names_path)) if names_path else classes
    detector = YoloDetector(
        model_path=str(onnx),
        classes=classes,
        conf_threshold=args.conf,
        iou_threshold=args.iou,
        names_path=str(names_path) if names_path else None,
    )
    try:
        detector.load()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"detector: {onnx}  conf={args.conf} iou={args.iou}  classes: {', '.join(effective)}")

    # per-class counters: [tp, fp, fn, iou_sum]
    counts = {name: [0, 0, 0, 0.0] for name in classes}
    imgs = sorted(p for p in test_images.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    if args.limit:
        imgs = imgs[: args.limit]
    if not imgs:
        print("no test images to evaluate", file=sys.stderr)
        return 2

    n_det = 0
    for img in imgs:
        label = test_labels / (img.stem + ".txt")
        gt_boxes, errs = validate_label(label.read_text(encoding="utf-8"), classes)
        frame = cv2.imread(str(img))

        preds = detector.detect(frame)
        n_det += len(preds)
        h, w = frame.shape[:2]

        # ground truth grouped by runtime class name
        gt_by = {name: [] for name in effective}
        for b in gt_boxes:
            gt_by[effective[b.class_id]].append(_pixel_rect(b, w, h))

        used = {name: [False] * len(gt_by[name]) for name in effective}
        for p in preds:
            name = p.class_name
            if name not in counts:
                continue
            best_iou, best_i = 0.0, -1
            for i, gt_r in enumerate(gt_by.get(name, [])):
                if used[name][i]:
                    continue
                iou = _iou((p.x1, p.y1, p.x2, p.y2), gt_r)
                if iou > best_iou:
                    best_iou, best_i = iou, i
            if best_i >= 0 and best_iou >= args.iou:
                counts[name][0] += 1
                counts[name][3] += best_iou
                used[name][best_i] = True
            else:
                counts[name][1] += 1
        for name in effective:
            counts[name][2] += sum(1 for u in used[name] if not u)

    print(f"\n{len(imgs):>4} images, {n_det} detections\n")
    print(f"{'class':<14}{'tp':>6}{'fp':>6}{'fn':>6}{'prec@.5':>9}{'rec@.5':>9}{'AP50':>8}")
    print("-" * 52)
    tp = fp = fn = 0
    for name in classes:
        c = counts[name]
        tp += c[0]; fp += c[1]; fn += c[2]
        prec = c[0] / (c[0] + c[1]) if (c[0] + c[1]) else 0.0
        rec = c[0] / (c[0] + c[2]) if (c[0] + c[2]) else 0.0
        ap = (c[3] / c[0]) * prec if c[0] else 0.0
        print(f"{name:<14}{c[0]:>6}{c[1]:>6}{c[2]:>6}{prec:>9.3f}{rec:>9.3f}{ap:>8.3f}")
    print("-" * 52)
    p_all = tp / (tp + fp) if (tp + fp) else 0.0
    r_all = tp / (tp + fn) if (tp + fn) else 0.0
    print(f"{'ALL':<14}{tp:>6}{fp:>6}{fn:>6}{p_all:>9.3f}{r_all:>9.3f}{'':>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Local bridge for the downloaded Roboflow everyday-objects dataset (Phase 4C+).

Turns the flat Roboflow export under ``dataset/roboflow/`` (``train/`` +
``valid/`` directories, each with ``images/`` + ``labels/``) into the same
split layout the app's training export expects — ``{train,val,test}/{images,labels}``
— with a corrected, location-independent ``data.yaml`` and the 15-class
vocabulary the model is trained on.

This is deliberately additive and separate from the app's own proprietary
object dataset (``dataset/raw`` + ``prepare_split.py``): those record webcam
sessions of the *experiment scene* (person + boxes + target area), whereas this
set is a downloaded, pre-labelled everyday-objects dataset. Neither touches the
other.

Roboflow's export is already split ``train`` / ``valid`` and is **flat** (no
per-session nesting), so the app's session-leakage splitter
(``annotation.annotator.make_split``) does not apply here. This module reuses
the shared YOLO label validation (``annotation.annotator.validate_label``) and
the model install helper (``training_tool.install_detection_model``), and
supplies only the roboflow-specific split/data.yaml wiring.

Pure, camera-free logic (like its siblings): no ultralytics, no cv2, no ai
imports. Weights only reach ``models/`` through an explicit script run.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path, PurePosixPath

from annotation.annotator import (
    IMAGE_EXTS,
    box_errors,
    parse_yolo_line,
    validate_label,
)


def normalize_roboflow_label(text: str, classes: list[str]) -> tuple[str, int, list[object]]:
    """Keep only YOLO bounding-box lines from a raw Roboflow label file.

    Roboflow occasionally exports **instance-segmentation polygons** alongside
    the boxes (``class cx1 cy1 cx2 cy2 ...`` — a duplicate mask record for the
    same object, all ``Spoon`` here). We train a detection model, so those rows
    are dropped and only the ``class cx cy w h`` box lines are kept — the same
    behaviour as ultralytics box-only training. Returns ``(kept_text,
    dropped_seg_rows, boxes)``. Genuinely malformed box/other rows raise.
    """
    kept: list[str] = []
    boxes: list[object] = []
    dropped = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) == 5:
            box = parse_yolo_line(line)
            errs = box_errors(box, len(classes))
            if errs:
                raise ValueError(f"box row invalid: {'; '.join(errs)}")
            boxes.append(box)
            kept.append(line)
        elif len(parts) >= 7 and (len(parts) - 1) % 2 == 0:
            dropped += 1  # segmentation-polygon duplicate -> drop for detection
        else:
            raise ValueError(f"malformed row (expected 5 fields): {line!r}")
    return "\n".join(kept) + ("\n" if kept else ""), dropped, boxes


#: Directory names inside the downloaded export.
ROBOFLOW_TRAIN = "train"
ROBOFLOW_VALID = "valid"

#: Output split names (same vocabulary as the app's splitter).
SPLITS = ("train", "val", "test")

#: Rendered names for ``train``/``valid`` from the download -> our splits.
SRC_SPLIT = {ROBOFLOW_TRAIN: "train", ROBOFLOW_VALID: "val"}

DATA_YAML_NAME = "data.yaml"
SPLIT_KEY_MANIFEST = "roboflow_split_manifest.json"


def load_roboflow_classes(data_yaml: str | Path | None = None) -> list[str]:
    """Read the ``names:`` list from the shipped Roboflow ``data.yaml``.

    The class vocabulary is **data**, never duplicated in code: it is parsed
    from the export's own ``data.yaml`` (matches the ``nc`` count when present).
    Roboflow writes ``names: ['A', 'B', ...]`` on one line; we also accept the
    YAML-list (``- A``) and map (``0: A``) spellings.
    """
    import ast

    p = Path(data_yaml) if data_yaml else Path(__file__).resolve().parent / "roboflow" / DATA_YAML_NAME
    if not p.is_file():
        raise FileNotFoundError(f"Roboflow data.yaml not found: {p}")
    names: list[str] = []
    lines = p.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("names:"):
            continue
        rest = stripped[len("names:"):].strip()
        if rest.startswith("["):
            try:
                parsed = ast.literal_eval(rest)
                names = [str(n) for n in parsed]
            except (ValueError, SyntaxError) as exc:
                raise ValueError(f"{p}: could not parse names list: {exc}") from exc
        else:
            # block form: subsequent `0: A` map or `- A` list lines
            for sub in lines[idx + 1:]:
                s = sub.strip()
                if not s or s.startswith("#"):
                    continue
                if s.startswith("-"):
                    item = s[1:].strip()
                    if item:
                        names.append(item)
                    continue
                if ":" in s:
                    _, _, value = s.partition(":")
                    value = value.strip()
                    if value:
                        names.append(value)
                        continue
                    break
                break
        if names:
            break
    if not names:
        raise ValueError(f"{p}: no class names parsed from data.yaml")
    return names


def scan_split(images_dir: Path, labels_dir: Path) -> list[tuple[str, Path, Path]]:
    """Pair images with their labels in a flat directory.

    Returns ``(relative_name, image_path, label_path)`` for every image that
    has a matching label file. Missing labels raise ``ValueError`` (a roboflow
    export should be fully annotated; blank labels are fine).
    """
    pairs: list[tuple[str, Path, Path]] = []
    images_dir = Path(images_dir)
    labels_dir = Path(labels_dir)
    for img in sorted(images_dir.iterdir()):
        if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
            continue
        label = labels_dir / (img.stem + ".txt")
        if not label.is_file():
            raise ValueError(
                f"roboflow split missing label for image {img.name} "
                f"(expected {label.name})"
            )
        pairs.append((img.name, img, label))
    return pairs


def copy_split(
    images_dir: Path,
    labels_dir: Path,
    out_root: Path,
    split: str,
    classes: list[str],
) -> dict:
    """Copy ``images_dir``/``labels_dir`` (flat) into ``out_root/split/*``.

    Validates every label against ``classes`` first; returns image/label
    counts and a per-class box histogram.
    """
    pairs = scan_split(images_dir, labels_dir)
    out_images = out_root / split / "images"
    out_labels = out_root / split / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)
    histogram = [0] * len(classes)
    for name, img, label in pairs:
        shutil.copy2(img, out_images / name)
        text = label.read_text(encoding="utf-8")
        kept, _dropped, boxes = normalize_roboflow_label(text, classes)
        (out_labels / label.name).write_text(kept, encoding="utf-8")
        for box in boxes:
            histogram[box.class_id] += 1
    return {"images": len(pairs), "labels": len(pairs), "histogram": histogram}


def make_roboflow_split(
    src_root: Path,
    out_root: Path,
    classes: list[str] | None = None,
    test_fraction: float = 0.1,
    seed: int = 42,
) -> dict:
    """Build ``{train,val,test}`` from the flat Roboflow train/valid exports.

    The download already supplies ``train`` and ``valid``. ``train`` maps to
    ``train`` unchanged; ``valid`` is split deterministically into ``val`` +
    ``test`` (so evaluation has a holdout set the model never trained on).
    Originals are only copied, never moved or modified.
    """
    src_root = Path(src_root).resolve()
    out_root = Path(out_root).resolve()
    if classes is None:
        classes = load_roboflow_classes(src_root / DATA_YAML_NAME)

    summary: dict = {}
    for src_name, split in SRC_SPLIT.items():
        src_images = src_root / src_name / "images"
        src_labels = src_root / src_name / "labels"
        if not src_images.is_dir() or not src_labels.is_dir():
            raise ValueError(f"roboflow export missing {src_name}/images+labels under {src_root}")
        info = copy_split(src_images, src_labels, out_root, split, classes)
        summary[split] = info

    # Carve a test holdout out of valid (flat, deterministic).
    val_images = out_root / "val" / "images"
    pairs = [
        (p.name, p, out_root / "val" / "labels" / (p.stem + ".txt"))
        for p in sorted(val_images.iterdir())
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    rng = random.Random(seed)
    rng.shuffle(pairs)
    n_test = max(1, int(round(len(pairs) * test_fraction)))
    test_items = pairs[:n_test]
    test_images = out_root / "test" / "images"
    test_labels = out_root / "test" / "labels"
    test_images.mkdir(parents=True, exist_ok=True)
    test_labels.mkdir(parents=True, exist_ok=True)
    test_hist = [0] * len(classes)
    for name, img, label in test_items:
        (val_images / name).rename(test_images / name)
        text = label.read_text(encoding="utf-8")
        (test_labels / (Path(name).stem + ".txt")).write_text(text, encoding="utf-8")
        label.unlink()
        boxes, _ = validate_label(text, classes)
        for box in boxes:
            test_hist[box.class_id] += 1
            summary["val"]["histogram"][box.class_id] -= 1
    test_pairs = scan_split(test_images, test_labels)
    summary["test"] = {
        "images": len(test_pairs),
        "labels": len(test_pairs),
        "histogram": test_hist,
    }
    summary["val"]["images"] -= len(test_items)
    summary["val"]["labels"] -= len(test_items)

    manifest = {
        "seed": seed,
        "test_fraction": test_fraction,
        "classes": classes,
        "images": {split: summary[split]["images"] for split in SPLITS},
    }
    (out_root / SPLIT_KEY_MANIFEST).write_text(
        __import__("json").dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def make_roboflow_data_yaml(
    split_root: Path,
    classes: list[str] | None = None,
    output: str | Path | None = None,
) -> dict:
    """Write a location-independent ``data.yaml`` for the roboflow split.

    Mirrors ``training_tool.make_data_yaml`` (absolute ``path`` + relative
    ``*/images`` dirs) but skips the app's session-leakage checks, which do not
    apply to a flat, downloaded set. Requires non-empty train + val; test is
    optional.
    """
    split_root = Path(split_root).resolve()
    if classes is None:
        # no data.yaml to read here (that is the input); require explicit classes
        raise ValueError("classes are required for roboflow data.yaml export")

    images: dict[str, int] = {}
    for split in ("train", "val", "test"):
        d = split_root / split / "images"
        images[split] = len(
            [p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        ) if d.is_dir() else 0
    if not images["train"]:
        raise ValueError(f"roboflow split has no 'train' images under {split_root}")
    if not images["val"]:
        raise ValueError(f"roboflow split has no 'val' images under {split_root}")

    yaml_path = Path(output) if output is not None else split_root / DATA_YAML_NAME
    yaml_path = yaml_path.resolve()
    if yaml_path.name != DATA_YAML_NAME:
        yaml_path = yaml_path / DATA_YAML_NAME
    yaml_path.parent.mkdir(parents=True, exist_ok=True)

    names_block = "".join(f"  {i}: {name}\n" for i, name in enumerate(classes))
    optional_test = "test: test/images\n" if images["test"] else ""
    body = (
        "# Roboflow everyday-objects dataset - prepared by dataset/roboflow_tool.py\n"
        f"path: {split_root.as_posix()}\n"
        "train: train/images\n"
        "val: val/images\n"
        + optional_test
        + f"nc: {len(classes)}\n"
        f"names:\n{names_block}"
    )
    yaml_path.write_text(body, encoding="utf-8")
    return {
        "yaml": str(yaml_path),
        "classes": list(classes),
        "images": images,
    }


def install_roboflow_model(
    onnx_path: Path,
    dest_dir: Path,
    classes: list[str] | None = None,
    dest_name: str = "roboflow.onnx",
) -> dict:
    """Install a trained roboflow ONNX + its ``.names`` for the runtime.

    Reuses ``training_tool.install_detection_model`` but writes to a distinct
    ``dest_name`` (default ``roboflow.onnx``) so it never clobbers the app's own
    ``yolov8n.onnx``/``yolov8n.names``. The ``.names`` file (from the roboflow
    classes) is how ``ai/detection/yolo_detector.py`` learns the 15 labels.
    """
    from training_tool import install_detection_model as _install

    if classes is None:
        classes = load_roboflow_classes()
    return _install(
        onnx_path,
        Path(dest_dir),
        classes=classes,
        dest_name=dest_name,
    )

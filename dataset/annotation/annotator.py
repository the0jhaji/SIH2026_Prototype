"""Pure logic for the local BAS annotation tool.

Everything needed to annotate keeps living here so the browser app, the
validation CLI and the tests share exactly one implementation:

- configurable classes (``annotation/classes.json``)
- YOLO label parsing / serializing (normalized ``class cx cy w h``)
- box validation (class id, coords in [0, 1], positive size)
- session identity + image scanning under ``dataset/raw``
- session-aware train/val/test split (never split one session across sets)
- dataset validation + cross-split session leakage detection

No web framework, no OpenCV, no production-code imports. Local only.
"""

from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_CLASSES = [
    "person",
    "knife",
    "pen",
    "red_box",
    "yellow_box",
    "floating_tool",
    "loose_cable",
    "bottle",
]
CLASSES_FILE = Path(__file__).resolve().parent / "classes.json"

#: Deterministic per-class box colors (indexed by class id).
PALETTE = ["#ef4444", "#38bdf8", "#eab308", "#f59e0b", "#a78bfa"]

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
SPLITS = ("train", "val", "test")
SPLIT_MANIFEST = "split_manifest.json"


# ---------------------------------------------------------------- classes
def load_classes(path: str | Path | None = None) -> list[str]:
    """Read the class list from ``classes.json`` (indexes are YOLO class ids)."""
    p = Path(path) if path else CLASSES_FILE
    data = json.loads(p.read_text(encoding="utf-8"))
    classes = [str(name).strip() for name in data.get("classes", []) if str(name).strip()]
    if not classes:
        raise ValueError(f"{p}: no classes configured")
    if len(set(classes)) != len(classes):
        raise ValueError(f"{p}: class names must be unique")
    return classes


def class_color(class_id: int) -> str:
    return PALETTE[class_id % len(PALETTE)]


# ---------------------------------------------------------- yolo label I/O
@dataclass(frozen=True)
class YoloBox:
    class_id: int
    cx: float
    cy: float
    w: float
    h: float

    def line(self) -> str:
        return f"{self.class_id} {self.cx:.6f} {self.cy:.6f} {self.w:.6f} {self.h:.6f}"

    def to_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "cx": self.cx,
            "cy": self.cy,
            "w": self.w,
            "h": self.h,
        }


def parse_yolo_line(line: str) -> YoloBox:
    """Parse one ``class cx cy w h`` line; raise ``ValueError`` if malformed."""
    parts = line.split()
    if len(parts) != 5:
        raise ValueError(f"expected 5 fields, got {len(parts)}: {line!r}")
    try:
        class_id = int(parts[0])
        cx, cy, w, h = (float(x) for x in parts[1:])
    except ValueError as exc:
        raise ValueError(f"non-numeric field: {line!r}") from exc
    return YoloBox(class_id, cx, cy, w, h)


def parse_label(text: str) -> list[YoloBox]:
    """Parse a whole label file into boxes (blank lines are allowed)."""
    boxes: list[YoloBox] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            boxes.append(parse_yolo_line(line))
        except ValueError as exc:
            raise ValueError(f"line {lineno}: {exc}") from exc
    return boxes


def serialize_label(boxes: list[YoloBox]) -> str:
    return "".join(box.line() + "\n" for box in boxes)


def normalize_box(class_id, x, y, w, h, img_w: int, img_h: int) -> YoloBox:
    """Turn pixel-space rects into a normalized YOLO box (clamped to image)."""
    cx = min(max(x + w / 2, 0.0), img_w) / img_w
    cy = min(max(y + h / 2, 0.0), img_h) / img_h
    return YoloBox(class_id, cx, cy, min(w, img_w) / img_w, min(h, img_h) / img_h)


def denormalize_box(box: YoloBox, img_w: int, img_h: int) -> tuple[float, float, float, float]:
    x = (box.cx - box.w / 2) * img_w
    y = (box.cy - box.h / 2) * img_h
    return x, y, box.w * img_w, box.h * img_h


# ------------------------------------------------------------- validation
def box_errors(box: YoloBox, n_classes: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(box.class_id, int) or not 0 <= box.class_id < n_classes:
        errors.append(f"class_id {box.class_id!r} out of range 0..{n_classes - 1}")
    for name, value in (("cx", box.cx), ("cy", box.cy), ("w", box.w), ("h", box.h)):
        if not 0.0 <= value <= 1.0:
            errors.append(f"{name} must be in [0, 1], got {value}")
    if box.w <= 0:
        errors.append("width must be positive")
    if box.h <= 0:
        errors.append("height must be positive")
    for name, center, half in (("cx", box.cx, box.w / 2), ("cy", box.cy, box.h / 2)):
        if center - half < -1e-6 or center + half > 1 + 1e-6:
            errors.append(f"box {name} extends outside the image")
    return errors


def validate_box(box: YoloBox, classes: list[str]) -> list[str]:
    return box_errors(box, len(classes))


def validate_label(text: str, classes: list[str]) -> tuple[list[YoloBox], list[str]]:
    """Parse + validate a label. Returns (boxes, errors); errors empty == valid."""
    try:
        boxes = parse_label(text)
    except ValueError as exc:
        return [], [f"malformed annotation: {exc}"]
    errors: list[str] = []
    for i, box in enumerate(boxes):
        for err in box_errors(box, len(classes)):
            errors.append(f"box #{i}: {err}")
    return boxes, errors


def validate_boxes_for_save(boxes: list[dict], classes: list[str]) -> list[str]:
    """Server-side guard before writing a label file (class id checked first)."""
    errors: list[str] = []
    for i, raw in enumerate(boxes):
        try:
            box = YoloBox(
                class_id=int(raw["class_id"]),
                cx=float(raw["cx"]),
                cy=float(raw["cy"]),
                w=float(raw["w"]),
                h=float(raw["h"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"box #{i}: invalid fields ({exc})")
            continue
        for err in box_errors(box, len(classes)):
            errors.append(f"box #{i}: {err}")
    return errors


# -------------------------------------------------------------- paths/data
def image_relpaths(root: Path) -> list[str]:
    """All images under ``root`` as sorted POSIX paths relative to it."""
    rels: set[str] = set()
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            rels.add(PurePosixPath(p.relative_to(root)).as_posix())
    return sorted(rels)


def session_of(rel: str) -> str:
    """A session is the image's directory (an entire recording take)."""
    return PurePosixPath(rel).parent.as_posix()


def label_rel(rel: str) -> str:
    return PurePosixPath(rel).with_suffix(".txt").as_posix()


def rel_to_path(root: Path, rel: str) -> Path:
    """Safely map an 'image' registry relative path onto ``root`` (no escapes)."""
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe relative path: {rel!r}")
    return root.joinpath(*pure.parts)


def is_annotated(raw_root: Path, annotations_root: Path, rel: str) -> bool:
    return rel_to_path(annotations_root, label_rel(rel)).is_file()


def progress(raw_root: Path, annotations_root: Path) -> dict:
    rels = image_relpaths(raw_root)
    annotated = sum(1 for rel in rels if is_annotated(raw_root, annotations_root, rel))
    total = len(rels)
    return {
        "total": total,
        "annotated": annotated,
        "percent": round(100 * annotated / total) if total else 0,
    }


# ------------------------------------------------------------ split logic
def assign_sessions(
    session_ids: list[str], train: float = 0.7, val: float = 0.2, test: float = 0.1, seed: int = 42
) -> dict[str, str]:
    """Deterministic session -> split assignment. One session, one split."""
    ids = list(session_ids)
    rng = random.Random(seed)
    rng.shuffle(ids)
    n = len(ids)
    n_val = min(int(n * val + 0.5), n)
    n_test = min(int(n * test + 0.5), n - n_val)
    n_train = n - n_val - n_test
    assignment: dict[str, str] = {}
    for split, count in (("train", n_train), ("val", n_val), ("test", n_test)):
        for session in ids[:count]:
            assignment[session] = split
        ids = ids[count:]
    return assignment


def make_split(
    raw_root: Path,
    output_root: Path,
    annotations_root: Path | None = None,
    classes: list[str] | None = None,
    train: float = 0.7,
    val: float = 0.2,
    test: float = 0.1,
    seed: int = 42,
) -> dict:
    """Copy sessions whole into ``train/val/test`` (images + matching labels).

    Returns a summary dict. Original ``raw`` files are never touched.
    """
    if classes is None:
        classes = load_classes()
    rels = image_relpaths(raw_root)
    sessions: dict[str, list[str]] = {}
    for rel in rels:
        sessions.setdefault(session_of(rel), []).append(rel)
    assignment = assign_sessions(sorted(sessions), train=train, val=val, test=test, seed=seed)

    summary = {split: {"sessions": 0, "images": 0, "labels": 0, "missing_labels": 0} for split in SPLITS}
    for session, images in sorted(sessions.items()):
        split = assignment[session]
        for rel in images:
            src = rel_to_path(raw_root, rel)
            dst = output_root / split / "images" / Path(*PurePosixPath(rel).parts)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            summary[split]["images"] += 1
            if annotations_root is not None:
                lrel = label_rel(rel)
                src_label = rel_to_path(annotations_root, lrel)
                if src_label.is_file():
                    dst_label = output_root / split / "labels" / Path(*PurePosixPath(lrel).parts)
                    dst_label.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_label, dst_label)
                    summary[split]["labels"] += 1
                else:
                    summary[split]["missing_labels"] += 1
        summary[split]["sessions"] += 1

    manifest = {
        "seed": seed,
        "ratios": {"train": train, "val": val, "test": test},
        "session_split": dict(sorted(assignment.items())),
    }
    (output_root / SPLIT_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return summary


def find_session_leakage(root: Path) -> list[str]:
    """Sessions that appear in more than one of train/val/test."""
    seen: dict[str, set[str]] = {}
    for split in SPLITS:
        images_dir = root / split / "images"
        if not images_dir.is_dir():
            continue
        for p in images_dir.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
                continue
            session = p.relative_to(images_dir).parent.as_posix()
            seen.setdefault(session, set()).add(split)
    return sorted(session for session, splits in seen.items() if len(splits) > 1)


# ------------------------------------------------------- dataset validation
@dataclass
class ValidationReport:
    errors: list[str]
    warnings: list[str]
    stats: dict

    @property
    def ok(self) -> bool:
        return not self.errors


def _stems_by_dir(images_root: Path) -> dict[str, set[str]]:
    """dir-relative path -> set of image stems (for missing-image checks)."""
    mapping: dict[str, set[str]] = {}
    for p in images_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            key = p.parent.relative_to(images_root).as_posix()
            mapping.setdefault(key, set()).add(p.stem)
    return mapping


def _check_labels_dir(
    images_root: Path, labels_root: Path, classes: list[str], prefix: str, errors: list[str], stats: dict
) -> None:
    images = sorted(
        p for p in images_root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    stats_for = stats.setdefault(prefix, {})
    stats_for["images"] = len(images)
    missing_labels = 0
    for img in images:
        rel = img.relative_to(images_root)
        if not img.is_file():
            errors.append(f"{prefix}: image does not exist: {rel.as_posix()}")
            continue
        label = rel_to_path(labels_root, label_rel(rel.as_posix()))
        if not label.is_file():
            missing_labels += 1
            errors.append(f"{prefix}: missing label for image {rel.as_posix()}")
            continue
        _, errs = validate_label(label.read_text(encoding="utf-8"), classes)
        if errs:
            errors.append(f"{prefix}: {rel.as_posix()}: {'; '.join(errs)}")
    stats_for["labels"] = len(images) - missing_labels
    stats_for["missing_labels"] = missing_labels
    seen = _stems_by_dir(images_root)
    for label in labels_root.rglob("*.txt"):
        lrel = label.relative_to(labels_root)
        if label.stem not in seen.get(lrel.parent.as_posix(), set()):
            errors.append(f"{prefix}: label without image: {lrel.as_posix()}")


def validate_dataset(
    root: Path, classes: list[str] | None = None, annotations_root: Path | None = None
) -> ValidationReport:
    """Validate raw + annotations pairing, the split output, and session leakage."""
    if classes is None:
        classes = load_classes()
    if annotations_root is None:
        annotations_root = root / "annotations"
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict = {"classes": len(classes)}

    raw_root = root / "raw"
    if raw_root.is_dir():
        rels = image_relpaths(raw_root)
        stats["raw"] = {"images": len(rels)}
        annotated = 0
        for rel in rels:
            label = rel_to_path(annotations_root, label_rel(rel))
            if label.is_file():
                annotated += 1
                _, errs = validate_label(label.read_text(encoding="utf-8"), classes)
                for err in errs:
                    errors.append(f"{rel}: {err}")
            else:
                warnings.append(f"not annotated yet: {rel}")
        stats["raw"]["annotated"] = annotated
    if annotations_root.is_dir():
        seen = _stems_by_dir(raw_root)
        for label in annotations_root.rglob("*.txt"):
            lrel = label.relative_to(annotations_root)
            if label.stem not in seen.get(lrel.parent.as_posix(), set()):
                errors.append(f"label without image: {lrel.as_posix()}")

    for split in SPLITS:
        images_dir = root / split / "images"
        labels_dir = root / split / "labels"
        if images_dir.is_dir():
            _check_labels_dir(images_dir, labels_dir, classes, split, errors, stats)

    for session in find_session_leakage(root):
        errors.append(f"session {session!r} appears in more than one split (leakage)")

    stats["errors"] = len(errors)
    stats["warnings"] = len(warnings)
    return ValidationReport(errors=errors, warnings=warnings, stats=stats)
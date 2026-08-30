"""Phase 4B tests: YOLO parsing, validation, session split, leakage, missing/malformed."""

import json
from pathlib import Path

import pytest

from annotation.annotator import (
    DEFAULT_CLASSES,
    YoloBox,
    assign_sessions,
    box_errors,
    denormalize_box,
    find_session_leakage,
    image_relpaths,
    label_rel,
    load_classes,
    make_split,
    normalize_box,
    parse_label,
    parse_yolo_line,
    rel_to_path,
    serialize_label,
    session_of,
    validate_boxes_for_save,
    validate_dataset,
    validate_label,
)


def make_raw_session(root: Path, session: str, frames: list[str]) -> Path:
    d = root / "raw" / "misc" / session
    d.mkdir(parents=True, exist_ok=True)
    for frame in frames:
        (d / frame).write_bytes(b"fake-jpeg")
    return d


def write_label(root: Path, rel: str, text: str) -> Path:
    path = root / "annotations" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------ classes
def test_classes_load_from_config_file(tmp_path) -> None:
    cfg = tmp_path / "classes.json"
    cfg.write_text(json.dumps({"classes": ["person", "robot"]}), encoding="utf-8")
    assert load_classes(cfg) == ["person", "robot"]


def test_class_validation_rejects_out_of_range_ids() -> None:
    classes = DEFAULT_CLASSES
    ok = YoloBox(0, 0.5, 0.5, 0.2, 0.2)
    assert box_errors(ok, len(classes)) == []
    bad = YoloBox(len(classes), 0.5, 0.5, 0.2, 0.2)
    assert any("class_id" in e for e in box_errors(bad, len(classes)))
    assert any("class_id" in e for e in validate_boxes_for_save([bad.to_dict()], classes))


def test_class_validation_rejects_negative_ids() -> None:
    errs = box_errors(YoloBox(-1, 0.5, 0.5, 0.2, 0.2), 5)
    assert any("class_id" in e for e in errs)


# ------------------------------------------------------------ coordinate validation
def test_coordinates_must_be_between_zero_and_one() -> None:
    for field, value in (("cx", 1.2), ("cy", -0.1), ("w", 1.5), ("h", 1.01)):
        box = YoloBox(0, 0.5, 0.5, 0.2, 0.2)
        box = YoloBox(0, box.cx if field != "cx" else value, box.cy if field != "cy" else value,
                      box.w if field != "w" else value, box.h if field != "h" else value)
        errs = box_errors(box, 5)
        assert any(f"{field} must be in [0, 1]" in e for e in errs), field


def test_width_height_must_be_positive() -> None:
    for value in (0.0, -0.5):
        errs = box_errors(YoloBox(0, 0.5, 0.5, value, 0.2), 5)
        assert any("width" in e for e in errs)
        errs = box_errors(YoloBox(0, 0.5, 0.5, 0.2, value), 5)
        assert any("height" in e for e in errs)


def test_box_must_stay_inside_image() -> None:
    errs = box_errors(YoloBox(0, 0.99, 0.5, 0.1, 0.2), 5)
    assert any("extends outside" in e for e in errs)


def test_normalize_round_trip() -> None:
    nb = normalize_box(2, 10, 20, 100, 200, img_w=1000, img_h=800)
    x, y, w, h = denormalize_box(nb, 1000, 800)
    assert (x, y, w, h) == pytest.approx((10, 20, 100, 200))


# ------------------------------------------------------------ YOLO parsing
def test_parse_label_round_trip() -> None:
    text = "0 0.500000 0.500000 0.200000 0.300000\n2 0.100000 0.900000 0.050000 0.100000\n"
    boxes = parse_label(text)
    assert len(boxes) == 2
    assert serialize_label(boxes) == text


def test_parse_label_skips_blank_lines() -> None:
    assert parse_label("  0 0.5 0.5 0.2 0.2\n\n")[0].class_id == 0


def test_parse_yolo_line_rejects_wrong_field_count() -> None:
    with pytest.raises(ValueError):
        parse_yolo_line("0 0.5 0.5 0.2")


def test_parse_yolo_line_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_yolo_line("abc 0.5 0.5 0.2 0.2")


def test_malformed_annotation_detected_by_validator(tmp_path) -> None:
    make_raw_session(tmp_path, "session_a", ["frame_000001.jpg"])
    write_label(tmp_path, "misc/session_a/frame_000001.txt", "0 0.5 0.5 0.2\n0 0.5 0.5 0.2 0.2\n")
    report = validate_dataset(tmp_path, classes=DEFAULT_CLASSES)
    assert not report.ok
    assert any("malformed annotation" in e for e in report.errors)


def test_validate_label_reports_malformed() -> None:
    boxes, errors = validate_label("0 0.5", DEFAULT_CLASSES)
    assert boxes == []
    assert errors and "malformed" in errors[0]


# ------------------------------------------------------------ dataset split
def test_assign_sessions_uses_each_session_once() -> None:
    sessions = [f"session_{i}" for i in range(10)]
    assignment = assign_sessions(sessions, seed=42)
    assert sorted(assignment) == sorted(sessions)
    sets = {"train": [], "val": [], "test": []}
    for session, split in assignment.items():
        sets[split].append(session)
    assert len(sets["train"]) == 7 and len(sets["val"]) == 2 and len(sets["test"]) == 1


def test_assign_sessions_is_deterministic() -> None:
    sessions = [f"session_{i}" for i in range(7)]
    assert assign_sessions(sessions, seed=7) == assign_sessions(sessions, seed=7)


def test_make_split_copies_images_and_labels_without_leakage(tmp_path) -> None:
    make_raw_session(tmp_path, "session_a", ["frame_000001.jpg", "frame_000002.jpg", "frame_000003.jpg"])
    make_raw_session(tmp_path, "session_b", ["frame_000001.jpg", "frame_000002.jpg"])
    for letter in "cdefg":
        make_raw_session(tmp_path, f"session_{letter}", ["frame_000001.jpg"])
    write_label(tmp_path, "misc/session_a/frame_000001.txt", "0 0.5 0.5 0.2 0.2\n")
    write_label(tmp_path, "misc/session_b/frame_000001.txt", "1 0.5 0.5 0.2 0.2\n")

    summary = make_split(tmp_path / "raw", tmp_path, annotations_root=tmp_path / "annotations", seed=42)

    assert sum(s["images"] for s in summary.values()) == 10
    per_split_sessions: dict[str, set[str]] = {split: set() for split in ("train", "val", "test")}
    for split in ("train", "val", "test"):
        images_dir = tmp_path / split / "images"
        for rel in image_relpaths(images_dir):
            per_split_sessions[split].add(session_of(rel))
    all_sessions = [s for sessions in per_split_sessions.values() for s in sessions]
    assert all(len(sessions) > 0 for sessions in per_split_sessions.values()), "every split got sessions"
    assert len(all_sessions) == 7, "all seven sessions must be copied"
    assert len(all_sessions) == len(set(all_sessions)), "session leaked across splits"
    assert find_session_leakage(tmp_path) == []


def test_make_split_keeps_split_manifest(tmp_path) -> None:
    make_raw_session(tmp_path, "session_a", ["frame_000001.jpg"])
    make_raw_session(tmp_path, "session_b", ["frame_000001.jpg"])
    make_split(tmp_path / "raw", tmp_path, seed=3)
    manifest = json.loads((tmp_path / "split_manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == 3
    assert set(manifest["session_split"]) == {"misc/session_a", "misc/session_b"}


# ------------------------------------------------------------ leakage
def test_session_leakage_detection(tmp_path) -> None:
    (tmp_path / "train" / "images" / "a").mkdir(parents=True)
    (tmp_path / "val" / "images" / "a").mkdir(parents=True)
    (tmp_path / "test" / "images" / "b").mkdir(parents=True)
    for split, session in (("train", "a"), ("val", "a"), ("test", "b")):
        (tmp_path / split / "images" / session / "frame.jpg").write_bytes(b"x")
    assert find_session_leakage(tmp_path) == ["a"]


def test_validate_dataset_reports_leakage(tmp_path) -> None:
    (tmp_path / "train" / "images" / "a").mkdir(parents=True)
    (tmp_path / "val" / "images" / "a").mkdir(parents=True)
    for split in ("train", "val"):
        (tmp_path / split / "images" / "a" / "frame.jpg").write_bytes(b"x")
    (tmp_path / "train" / "labels" / "a").mkdir(parents=True)
    (tmp_path / "train" / "labels" / "a" / "frame.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    report = validate_dataset(tmp_path, classes=DEFAULT_CLASSES)
    assert not report.ok
    assert any("more than one split" in e for e in report.errors)


# ------------------------------------------------------------ missing / malformed
def test_missing_image_detection_label_orphan(tmp_path) -> None:
    make_raw_session(tmp_path, "session_a", ["frame_000001.jpg"])
    write_label(tmp_path, "misc/session_a/frame_000001.txt", "0 0.5 0.5 0.2 0.2\n")
    (tmp_path / "raw" / "misc" / "session_a" / "frame_000001.jpg").unlink()
    report = validate_dataset(tmp_path, classes=DEFAULT_CLASSES)
    assert any("label without image" in e for e in report.errors)


def test_missing_label_detection_in_split(tmp_path) -> None:
    make_raw_session(tmp_path, "session_a", ["frame_000001.jpg"])
    (tmp_path / "train" / "images" / "misc" / "session_a").mkdir(parents=True)
    (tmp_path / "train" / "images" / "misc" / "session_a" / "frame_000001.jpg").write_bytes(b"x")
    report = validate_dataset(tmp_path, classes=DEFAULT_CLASSES)
    assert any("missing label" in e for e in report.errors)


def test_validate_dataset_ok_case(tmp_path) -> None:
    make_raw_session(tmp_path, "session_a", ["frame_000001.jpg"])
    make_raw_session(tmp_path, "session_b", ["frame_000001.jpg", "frame_000002.jpg"])
    write_label(tmp_path, "misc/session_a/frame_000001.txt", "0 0.5 0.5 0.2 0.2\n")
    for frame in ("frame_000001.txt", "frame_000002.txt"):
        write_label(tmp_path, f"misc/session_b/{frame}", "0 0.5 0.5 0.2 0.2\n")
    make_split(tmp_path / "raw", tmp_path, annotations_root=tmp_path / "annotations", classes=DEFAULT_CLASSES, seed=1)
    report = validate_dataset(tmp_path, classes=DEFAULT_CLASSES)
    assert report.ok, report.errors


def test_validate_boxes_before_save_rejects_bad_class(tmp_path) -> None:
    errors = validate_boxes_for_save(
        [{"class_id": 99, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}], DEFAULT_CLASSES
    )
    assert any("class_id" in e for e in errors)


def test_rel_path_helpers() -> None:
    assert label_rel("misc/session_a/frame_000001.jpg") == "misc/session_a/frame_000001.txt"
    assert session_of("misc/session_a/frame_000001.jpg") == "misc/session_a"
    with pytest.raises(ValueError):
        rel_to_path(Path("x"), "../escape.jpg")
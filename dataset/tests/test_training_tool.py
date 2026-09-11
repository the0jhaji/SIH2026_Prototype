"""Tests for the Phase 4C training bridge (`dataset/training_tool.py`).

Covers the validated data.yaml export (labels, class ids, leakage) and the
ONNX + .names install into the runtime model directory. Pure logic — no
ultralytics, no camera, no display needed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from annotation.annotator import load_classes, make_split
from training_tool import class_histogram, install_detection_model, make_data_yaml

classes_default = load_classes()


@pytest.fixture
def split_dataset(tmp_path):
    """A tiny annotated raw set (4 sessions × 3 frames) split 50/50 train/val."""
    classes = classes_default
    raw = tmp_path / "raw"
    annotations = tmp_path / "annotations"
    for s_idx in range(4):
        (raw / f"s{s_idx}").mkdir(parents=True, exist_ok=True)
        (annotations / f"s{s_idx}").mkdir(parents=True, exist_ok=True)
        for i in range(1, 4):
            img = raw / f"s{s_idx}" / f"frame_{i:06d}.jpg"
            img.write_bytes(b"\xff\xd8\xff")
            cls = (s_idx + i) % len(classes)
            (annotations / f"s{s_idx}" / f"frame_{i:06d}.txt").write_text(
                f"{cls} 0.5 0.5 0.2 0.2\n", encoding="utf-8"
            )
    split_root = tmp_path / "split"
    stats = make_split(
        raw,
        split_root,
        annotations_root=annotations,
        classes=classes,
        train=0.5,
        val=0.5,
        test=0.0,
        seed=1,
    )
    for split in ("train", "val"):
        assert stats[split]["labels"] == 6 and stats[split]["missing_labels"] == 0
    return split_root, classes


def test_make_data_yaml_writes_valid_yaml(split_dataset, tmp_path):
    split_root, classes = split_dataset
    output = tmp_path / "dir" / "data.yaml"
    summary = make_data_yaml(split_root, classes=classes, output=output)
    assert summary["yaml"] == str(output.resolve())
    assert summary["images"] == {"train": 6, "val": 6}
    assert summary["classes"] == classes

    text = output.read_text(encoding="utf-8")
    assert f"path: {split_root.as_posix()}" in text
    assert "train: train/images" in text
    assert "val: val/images" in text
    assert "test: test/images" not in text  # test empty -> omitted
    assert f"nc: {len(classes)}" in text
    for i, name in enumerate(classes):
        assert f"  {i}: {name}" in text


def test_make_data_yaml_histogram_counts_boxes(split_dataset, tmp_path):
    split_root, classes = split_dataset
    summary = make_data_yaml(split_root, classes=classes, output=tmp_path / "data.yaml")
    total = sum(summary["histogram"]["train"]) + sum(summary["histogram"]["val"])
    assert total == 12  # 4 sessions x 3 labelled frames


def test_class_histogram_matches_labels(split_dataset):
    split_root, _ = split_dataset
    hist = class_histogram(split_root, len(classes_default))
    assert sum(hist["train"]) + sum(hist["val"]) == 12


def test_make_data_yaml_rejects_missing_label(split_dataset, tmp_path):
    split_root, classes = split_dataset
    missing = next((split_root / "train" / "labels").rglob("*.txt"))
    missing.unlink()
    with pytest.raises(ValueError, match="missing label"):
        make_data_yaml(split_root, classes=classes, output=tmp_path / "data.yaml")


def test_make_data_yaml_rejects_session_leakage(split_dataset, tmp_path):
    split_root, classes = split_dataset
    session = next((split_root / "train" / "images").iterdir())
    shutil.copytree(
        session, split_root / "val" / "images" / session.name
    )
    labels_source = split_root / "train" / "labels" / session.name
    shutil.copytree(labels_source, split_root / "val" / "labels" / session.name)
    with pytest.raises(ValueError, match="more than one split"):
        make_data_yaml(split_root, classes=classes, output=tmp_path / "data.yaml")


def test_make_data_yaml_requires_train_and_val(tmp_path):
    classes = classes_default
    only_train = tmp_path / "only_train"
    (only_train / "train" / "images").mkdir(parents=True)
    (only_train / "train" / "labels").mkdir(parents=True)
    (only_train / "train" / "images" / "a.jpg").write_bytes(b"x")
    (only_train / "train" / "labels" / "a.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="'val' images"):
        make_data_yaml(only_train, classes=classes, output=tmp_path / "data.yaml")


def test_make_data_yaml_rejects_out_of_range_class(tmp_path):
    classes = ["person", "red_box"]
    split_root = tmp_path / "split"
    (split_root / "train" / "images").mkdir(parents=True)
    (split_root / "train" / "labels").mkdir(parents=True)
    (split_root / "val" / "images").mkdir(parents=True)
    (split_root / "val" / "labels").mkdir(parents=True)
    (split_root / "train" / "images" / "a.jpg").write_bytes(b"x")
    (split_root / "train" / "labels" / "a.txt").write_text("2 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    (split_root / "val" / "images" / "b.jpg").write_bytes(b"x")
    (split_root / "val" / "labels" / "b.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="class_id"):
        make_data_yaml(split_root, classes=classes, output=tmp_path / "data.yaml")


def test_install_detection_model_copies_weights_and_names(tmp_path):
    src = tmp_path / "best.onnx"
    src.write_bytes(b"\x00\x01onnx")
    dest_dir = tmp_path / "models" / "detection"
    result = install_detection_model(src, dest_dir, classes=["person", "red_box"])
    assert Path(result["onnx"]).read_bytes() == b"\x00\x01onnx"
    assert Path(result["names"]).read_text(encoding="utf-8") == "person\nred_box\n"
    assert result["classes"] == ["person", "red_box"]


def test_install_detection_model_defaults_classes(tmp_path):
    src = tmp_path / "best.onnx"
    src.write_bytes(b"onnx")
    result = install_detection_model(src, tmp_path / "models" / "detection")
    assert result["classes"] == classes_default
    assert Path(result["names"]).read_text(encoding="utf-8") == "\n".join(classes_default) + "\n"


def test_install_detection_model_requires_source(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        install_detection_model(tmp_path / "missing.onnx", tmp_path / "models")
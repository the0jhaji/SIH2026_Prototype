"""Tests for the Roboflow dataset bridge (`dataset/roboflow_tool.py`).

Pure logic only — no ultralytics, no cv2, no camera. Builds synthetic flat
Roboflow-style exports (``train/`` + ``valid/`` with ``images/`` + ``labels/``)
and checks the split, validation and data.yaml wiring.

Note: `roboflow_tool` imports `annotation.annotator`, so these tests run from
the repo root with the backend venv (`dataset/tests/conftest.py` puts both the
`dataset/` and `backend/` dirs on `sys.path`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roboflow_tool import (
    SPLITS,
    load_roboflow_classes,
    make_roboflow_data_yaml,
    make_roboflow_split,
    scan_split,
)

CLASSES = ["Bag", "Book", "Bottle", "Cup"]


def make_flat_export(root: Path, n_train: int = 8, n_valid: int = 6) -> Path:
    """A minimal Roboflow-style export: train/images+labels, valid/images+labels."""
    src = root / "roboflow"
    for split in ("train", "valid"):
        for i in range(n_train if split == "train" else n_valid):
            img = src / split / "images" / f"{i:06d}.jpg"
            img.parent.mkdir(parents=True, exist_ok=True)
            img.write_bytes(b"\xff\xd8\xff")
            label = src / split / "labels" / f"{i:06d}.txt"
            label.parent.mkdir(parents=True, exist_ok=True)
            cls = i % len(CLASSES)
            label.write_text(f"{cls} 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    data_yaml = src / "data.yaml"
    names_block = "".join(f"  {i}: {n}\n" for i, n in enumerate(CLASSES))
    data_yaml.write_text(f"nc: {len(CLASSES)}\nnames:\n{names_block}", encoding="utf-8")
    return src


def test_load_roboflow_classes(tmp_path):
    src = make_flat_export(tmp_path, n_train=1, n_valid=1)
    assert load_roboflow_classes(src / "data.yaml") == CLASSES


def test_load_roboflow_classes_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_roboflow_classes(tmp_path / "nope.yaml")


def test_make_roboflow_split_builds_train_val_test(tmp_path):
    src = make_flat_export(tmp_path, n_train=8, n_valid=6)
    cls = load_roboflow_classes(src / "data.yaml")
    out = tmp_path / "out"
    summary = make_roboflow_split(src, out, classes=cls, test_fraction=0.5, seed=1)

    assert summary["train"]["images"] == 8
    assert summary["val"]["images"] == 3  # 6 -> 3 test (0.5)
    assert summary["test"]["images"] == 3
    # every split retains matching images+labels
    for split in SPLITS:
        imgs = list((out / split / "images").glob("*.jpg"))
        labels = list((out / split / "labels").glob("*.txt"))
        assert len(imgs) == summary[split]["images"]
        assert len(imgs) == len(labels)
        assert {i.stem for i in imgs} == {l.stem for l in labels}
        scan_split(out / split / "images", out / split / "labels")


def test_split_is_disjoint_between_splits(tmp_path):
    src = make_flat_export(tmp_path, n_train=8, n_valid=6)
    out = tmp_path / "out"
    make_roboflow_split(src, out, classes=CLASSES, test_fraction=0.5, seed=1)
    stems = {
        split: {p.stem for p in (out / split / "images").glob("*.jpg")}
        for split in SPLITS
    }
    assert not (stems["train"] & stems["val"] & stems["test"])
    assert not stems["val"] & stems["test"]


def test_split_rejects_out_of_range_class(tmp_path):
    src = make_flat_export(tmp_path, n_train=1, n_valid=1)
    # tamper one train label to an invalid class id
    bad = next((src / "train" / "labels").glob("*.txt"))
    bad.write_text(f"{len(CLASSES)} 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="class_id"):
        make_roboflow_split(src, tmp_path / "out", classes=CLASSES)


def test_split_rejects_missing_label(tmp_path):
    src = make_flat_export(tmp_path, n_train=1, n_valid=1)
    next((src / "train" / "labels").glob("*.txt")).unlink()
    with pytest.raises(ValueError, match="missing label"):
        make_roboflow_split(src, tmp_path / "out", classes=CLASSES)


def test_make_roboflow_data_yaml(tmp_path):
    src = make_flat_export(tmp_path, n_train=4, n_valid=6)
    out = tmp_path / "out"
    make_roboflow_split(src, out, classes=CLASSES, test_fraction=0.5, seed=1)
    info = make_roboflow_data_yaml(out, classes=CLASSES, output=tmp_path / "cfg")
    assert info["classes"] == CLASSES
    assert info["images"] == {"train": 4, "val": 3, "test": 3}
    text = Path(info["yaml"]).read_text(encoding="utf-8")
    assert f"path: {out.resolve().as_posix()}" in text
    assert "train: train/images" in text
    assert "val: val/images" in text
    assert "test: test/images" in text
    assert f"nc: {len(CLASSES)}" in text
    for i, name in enumerate(CLASSES):
        assert f"  {i}: {name}" in text


def test_make_roboflow_data_yaml_requires_train_and_val(tmp_path):
    src = make_flat_export(tmp_path, n_train=0, n_valid=6)
    # n_train=0 leaves valid only; make train empty intentionally by building a
    # split from scratch with no train images
    out = tmp_path / "out"
    # build a valid split with train present, then delete train images
    src2 = make_flat_export(tmp_path / "x", n_train=4, n_valid=4)
    make_roboflow_split(src2, out, classes=CLASSES, test_fraction=0.5, seed=1)
    for p in (out / "train" / "images").glob("*"):
        p.unlink()
    with pytest.raises(ValueError, match="'train' images"):
        make_roboflow_data_yaml(out, classes=CLASSES, output=tmp_path / "cfg")

"""Tests for dataset session creation and configuration.

Pure logic only — no camera, no OpenCV window, no physical device.
"""

import json

import pytest

from dataset_tool import (
    MANIFEST_FIELDS,
    BACKEND_DIR,
    DatasetConfig,
    Session,
    add_manifest_row,
    create_session,
    ensure_layout,
    frame_filename,
    slugify,
    write_metadata,
)

RAW = "raw"
FRAMES = "frames"
ANNOTATIONS = "annotations"


def test_defaults_mirror_backend_camera_config() -> None:
    cfg = DatasetConfig()
    assert (cfg.camera_index, cfg.width, cfg.height, cfg.fps) == (0, 1280, 720, 30)


def test_default_interval_is_one_second() -> None:
    assert DatasetConfig().interval == 1.0


def test_invalid_configurations_rejected() -> None:
    bad = [
        {"width": 0},
        {"width": -1},
        {"height": 0},
        {"fps": 0},
        {"fps": -5},
        {"interval": 0},
        {"interval": -1},
        {"camera_index": -1},
    ]
    for kwargs in bad:
        with pytest.raises(ValueError):
            DatasetConfig(**kwargs)


def test_label_slugified() -> None:
    assert DatasetConfig(label="PICK RED BOX").session_label == "pick_red_box"
    assert DatasetConfig(label="pick-red").session_label == "pick_red"
    assert slugify("  ") == "misc"


def test_create_session_creates_unique_dirs(tmp_path) -> None:
    cfg = DatasetConfig(output_dir=tmp_path)
    s1 = create_session(cfg)
    s2 = create_session(cfg)
    assert isinstance(s1, Session)
    assert s1.session_id != s2.session_id
    assert s1.root.exists() and s2.root.exists()
    assert s1.root.name.startswith("session_")
    assert s1.root.parent.name == "misc"
    assert s1.root.parent.parent.name == RAW


def test_create_session_groups_by_label(tmp_path) -> None:
    s = create_session(DatasetConfig(output_dir=tmp_path, label="PICK_RED"))
    assert s.root.parent.name == "pick_red"


def test_create_session_layout_and_initial_metadata(tmp_path) -> None:
    cfg = DatasetConfig(output_dir=tmp_path)
    s = create_session(cfg)
    assert RAW in {d.name for d in cfg.output_dir.iterdir()}
    meta = json.loads((s.root / "metadata.json").read_text(encoding="utf-8"))
    assert meta["session_id"] == s.session_id
    assert meta["camera"] == {"index": 0, "width": 1280, "height": 720, "fps": 30, "mock": False}
    assert meta["recorder"]["frames_saved"] == 0
    assert meta["storage"] == "local-only; never uploaded"


def test_ensure_layout_creates_skeleton(tmp_path) -> None:
    out = tmp_path / "nested" / "dataset"
    ensure_layout(out)
    assert {d.name for d in out.iterdir()} == {RAW, FRAMES, ANNOTATIONS}


def test_frame_filename_sequential() -> None:
    assert frame_filename(1) == "frame_000001.jpg"
    assert frame_filename(123) == "frame_000123.jpg"


def test_metadata_refresh_records_ended_at_and_count(tmp_path) -> None:
    cfg = DatasetConfig(output_dir=tmp_path)
    s = create_session(cfg)
    write_metadata(s, cfg, ended_at="2026-01-02T03:04:05+00:00", frames_saved=42)
    meta = json.loads((s.root / "metadata.json").read_text(encoding="utf-8"))
    assert meta["ended_at"] == "2026-01-02T03:04:05+00:00"
    assert meta["recorder"]["frames_saved"] == 42


def test_manifest_appends_header_and_rows(tmp_path) -> None:
    s = create_session(DatasetConfig(output_dir=tmp_path))
    add_manifest_row(s, 1, "2026-01-01T00:00:01+00:00", 1000)
    add_manifest_row(s, 2, "2026-01-01T00:00:02+00:00", 2000)
    lines = (s.root / "manifest.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(MANIFEST_FIELDS)
    assert lines[1] == "1,2026-01-01T00:00:01+00:00,1000"
    assert lines[2] == "2,2026-01-01T00:00:02+00:00,2000"


def test_backend_dir_resolution_points_at_repo_backend() -> None:
    assert BACKEND_DIR.is_dir()
    assert (BACKEND_DIR / "camera" / "capture.py").is_file()
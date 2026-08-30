"""Tests for the Phase 5B ACTIVITY dataset tooling (`dataset/activity_tool.py`).

The canonical activity vocabulary is read from `experiment/experiment.json` —
these tests pin that single source of truth.
"""

from __future__ import annotations

import csv
import json

import pytest

from activity_tool import (
    EXPERIMENT_JSON,
    MANIFEST_FIELDS,
    ActivityConfig,
    ActivitySession,
    activity_frame_filename,
    add_activity_manifest_row,
    create_activity_session,
    is_valid_activity,
    load_activities,
    write_activity_metadata,
)

EXPECTED_ACTIVITIES = [
    "APPROACH",
    "OPEN_BOX",
    "PICK_RED",
    "PLACE_RED",
    "PICK_YELLOW",
    "PLACE_YELLOW",
    "COMPLETE",
]


@pytest.fixture
def config(tmp_path) -> ActivityConfig:
    return ActivityConfig(activity="PICK_RED", output_dir=tmp_path)


def test_load_activities_matches_canonical_experiment() -> None:
    payload = json.loads(EXPERIMENT_JSON.read_text(encoding="utf-8"))
    assert load_activities() == payload["activities"]


def test_load_activities_is_canonical_vocabulary() -> None:
    assert load_activities() == EXPECTED_ACTIVITIES


def test_all_canonical_activities_are_valid() -> None:
    for activity in EXPECTED_ACTIVITIES:
        assert is_valid_activity(activity)
        ActivityConfig(activity=activity)


def test_invalid_activity_is_rejected() -> None:
    assert not is_valid_activity("BOGUS")
    with pytest.raises(ValueError, match="BOGUS"):
        ActivityConfig(activity="BOGUS")


def test_activity_config_validates_camera_fields() -> None:
    with pytest.raises(ValueError):
        ActivityConfig(activity="APPROACH", width=0)
    with pytest.raises(ValueError):
        ActivityConfig(activity="APPROACH", fps=-1)
    with pytest.raises(ValueError):
        ActivityConfig(activity="APPROACH", interval=0)
    with pytest.raises(ValueError):
        ActivityConfig(activity="APPROACH", camera_index=-2)


def test_session_created_under_activity_layout(config) -> None:
    session = create_activity_session(config)
    assert isinstance(session, ActivitySession)
    assert session.activity == "PICK_RED"
    assert session.root.name.startswith("session_")
    assert session.root.parent.name == "PICK_RED"
    assert session.root.parent.parent.name == "activity"
    assert (session.root / "metadata.json").exists()


def test_sessions_are_unique(config) -> None:
    first = create_activity_session(config)
    second = create_activity_session(config)
    assert first.session_id != second.session_id
    assert first.root != second.root


def test_activity_directories_are_isolated(tmp_path) -> None:
    create_activity_session(ActivityConfig(activity="APPROACH", output_dir=tmp_path))
    create_activity_session(ActivityConfig(activity="COMPLETE", output_dir=tmp_path))
    approach_dir = tmp_path / "activity" / "APPROACH"
    complete_dir = tmp_path / "activity" / "COMPLETE"
    assert approach_dir.is_dir()
    assert complete_dir.is_dir()
    assert len(list(approach_dir.glob("session_*"))) == 1
    assert len(list(complete_dir.glob("session_*"))) == 1


def test_metadata_round_trip(config) -> None:
    session = create_activity_session(config)
    path = write_activity_metadata(
        session, config, ended_at="2026-08-30T10:00:01+00:00", frame_count=7
    )
    assert path == session.root / "metadata.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["activity"] == "PICK_RED"
    assert payload["session_id"] == session.session_id
    assert payload["started_at"] == session.started_at_iso
    assert payload["ended_at"] == "2026-08-30T10:00:01+00:00"
    assert payload["frame_count"] == 7
    assert payload["interval"] == config.interval
    assert payload["source"] == "webcam"
    assert payload["schema"] == "bas-activity-session/1"
    assert payload["camera"] == {
        "index": 0,
        "width": 1280,
        "height": 720,
        "fps": 30,
        "mock": False,
    }


def test_metadata_source_mock(tmp_path) -> None:
    cfg = ActivityConfig(activity="OPEN_BOX", output_dir=tmp_path, mock=True)
    session = create_activity_session(cfg)
    payload = json.loads((session.root / "metadata.json").read_text(encoding="utf-8"))
    assert payload["source"] == "mock"
    assert payload["camera"]["mock"] is True


def test_manifest_format_and_rows(config) -> None:
    session = create_activity_session(config)
    row1 = add_activity_manifest_row(session, 1, "2026-08-30T10:00:00+00:00", 1725000000000, "frame_000001.jpg")
    row2 = add_activity_manifest_row(session, 2, "2026-08-30T10:00:01+00:00", 1725000001000, "frame_000002.jpg")
    assert row1 == row2 == session.root / "manifest.csv"
    with session.root.joinpath("manifest.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == MANIFEST_FIELDS
    assert rows[1] == ["1", "2026-08-30T10:00:00+00:00", "1725000000000", "frame_000001.jpg"]
    assert rows[2] == ["2", "2026-08-30T10:00:01+00:00", "1725000001000", "frame_000002.jpg"]
    assert len(rows) == 3


def test_frame_naming_sequence() -> None:
    assert activity_frame_filename(1) == "frame_000001.jpg"
    assert activity_frame_filename(42) == "frame_000042.jpg"
    assert activity_frame_filename(123456) == "frame_123456.jpg"


def test_camera_settings_reuse(config) -> None:
    settings = config.to_camera_settings()
    assert settings.mock is False
    assert settings.width == config.width
    assert settings.height == config.height
    assert settings.fps == config.fps
    assert settings.camera_index == config.camera_index
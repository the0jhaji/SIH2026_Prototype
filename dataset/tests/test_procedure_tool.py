"""Tests for the procedure ground-truth labeller (`dataset/procedure_tool.py`).

Pure logic: no camera, no OpenCV, no network. The point of these tests is that
the tool stays *honest* - it labels from the canonical experiment, never invents
a step, and says so in its output rather than guessing.
"""

from __future__ import annotations

import csv
import json

import pytest

from procedure_tool import (
    NO_STEP,
    PROCEDURE_FIELDS,
    ProcedureStep,
    classes_from_labels,
    label_rows,
    label_session,
    load_procedure,
    parse_classes,
    read_manifest,
    step_for_classes,
    write_labels,
)

STEP = ProcedureStep(id="s1", order=1, activity="PICK", required=("red_box",))
OTHER = ProcedureStep(id="s2", order=2, activity="PLACE", required=("red_box", "target_area"))
#: A step that requires nothing must never be claimed to be evidenced.
VACUOUS = ProcedureStep(id="s0", order=0, activity="NOTHING", required=())


def test_steps_come_from_the_canonical_experiment() -> None:
    steps = load_procedure()
    assert [s.activity for s in steps] == [
        "APPROACH",
        "OPEN_BOX",
        "PICK_RED",
        "PLACE_RED",
        "PICK_YELLOW",
        "PLACE_YELLOW",
        "COMPLETE",
    ]
    assert steps[0].required == ("person",)
    assert steps[3].required == ("red_box", "target_area")
    # A custom definition is honoured instead of hardcoded.
    assert load_procedure(_write_json({"steps": [{"id": "a", "activity": "X", "expectedObjects": ["q"]}]}))[
        0
    ].required == ("q",)


def test_step_for_classes_requires_every_object() -> None:
    steps = [STEP, OTHER]
    assert step_for_classes(steps, {"red_box"}) == STEP
    assert step_for_classes(steps, {"red_box", "target_area", "person"}) == STEP
    # target_area missing -> the PLACE step is not evidenced.
    assert step_for_classes(steps, {"red_box", "person"}) == STEP
    assert step_for_classes(steps, {"person"}) is None
    assert step_for_classes(steps, set()) is None


def test_a_step_with_no_objects_is_never_claimed() -> None:
    """A step that requires nothing has no evidence, so it is skipped."""
    # The vacuous step is passed over, and PICK still needs its object.
    assert step_for_classes([VACUOUS, STEP], set()) is None
    assert step_for_classes([VACUOUS, STEP], {"red_box"}) == STEP
    assert step_for_classes([VACUOUS], {"anything"}) is None


def test_start_order_prevents_jumping_ahead() -> None:
    steps = [STEP, OTHER]
    # Even with both objects visible, the operator must not skip the pick.
    assert step_for_classes(steps, {"red_box", "target_area"}, start_order=1) == STEP
    assert step_for_classes(steps, {"red_box", "target_area"}, start_order=2) == OTHER


def test_labels_advance_and_never_go_backwards() -> None:
    steps = [STEP, OTHER]
    rows = [
        {"index": 1, "classes": "red_box"},
        {"index": 2, "classes": "red_box;target_area"},
        # After PLACE, the pick must not be re-emitted.
        {"index": 3, "classes": "red_box"},
        {"index": 4, "classes": "person"},
    ]
    out = label_rows(rows, steps)
    assert [r["activity"] for r in out] == ["PICK", "PLACE", NO_STEP, NO_STEP]
    assert [r["step_order"] for r in out] == [1, 2, NO_STEP, NO_STEP]


def test_unknown_frames_are_labelled_not_step_not_guessed() -> None:
    out = label_rows([{"index": 1, "classes": "bottle"}], [STEP])
    assert out[0]["step_id"] == NO_STEP
    assert out[0]["classes"] == "bottle"  # the observation is still recorded


def test_classes_by_frame_wins_over_the_manifest() -> None:
    rows = [{"index": 1, "classes": "bottle"}]
    out = label_rows(rows, [STEP], classes_by_frame=[{"red_box"}])
    assert out[0]["activity"] == "PICK"


def test_parse_classes_is_defensive() -> None:
    assert parse_classes("red_box;target_area") == {"red_box", "target_area"}
    assert parse_classes("") == set()
    assert parse_classes(None) == set()


def test_malformed_label_file_yields_no_classes(tmp_path) -> None:
    """A bad label must not become a step label."""
    (tmp_path / "f.txt").write_text("not-a-label\n", encoding="utf-8")
    assert classes_from_labels(tmp_path, ["person", "red_box"], "f.txt") == set()
    (tmp_path / "missing.txt").write_text("", encoding="utf-8")
    assert classes_from_labels(tmp_path, ["person", "red_box"], "nope.txt") == set()
    assert classes_from_labels(tmp_path / "absent", ["person"], "f.txt") == set()


def test_classes_are_read_from_yolo_labels(tmp_path) -> None:
    # YOLO class ids are 0-based indexes into classes.json.
    (tmp_path / "a.txt").write_text("3 0.5 0.5 0.2 0.2\n1 0.2 0.2 0.1 0.1\n", encoding="utf-8")
    assert classes_from_labels(tmp_path, ["person", "red_box", "yellow_box", "x"], "a.txt") == {
        "red_box",
        "x",
    }
    # A blank label is a valid background frame: present, but empty.
    (tmp_path / "b.txt").write_text("", encoding="utf-8")
    assert classes_from_labels(tmp_path, ["person", "red_box"], "b.txt") == set()


def test_label_session_writes_a_csv(tmp_path) -> None:
    session = tmp_path / "session_1"
    session.mkdir()
    with (session / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["index", "filename", "classes"])
        writer.writeheader()
        writer.writerow({"index": 1, "filename": "f1.jpg", "classes": "person"})
        writer.writerow({"index": 2, "filename": "f2.jpg", "classes": "person;red_box"})
    path, rows = label_session(session, [STEP, OTHER])
    assert path.name == "procedure_labels.csv"
    assert [r["activity"] for r in rows] == [NO_STEP, "PICK"]
    written = list(csv.DictReader(path.open(encoding="utf-8")))
    assert list(written[0]) == PROCEDURE_FIELDS
    assert read_manifest(session)[1]["filename"] == "f2.jpg"


def test_out_path_and_explicit_steps_are_honoured(tmp_path) -> None:
    session = tmp_path / "s"
    session.mkdir()
    (session / "manifest.csv").write_text("index,classes\n1,red_box\n", encoding="utf-8")
    out = tmp_path / "nested" / "labels.csv"
    out.parent.mkdir()
    path, rows = label_session(session, [STEP], out)
    assert path == out
    assert rows[0]["activity"] == "PICK"


def test_write_labels_uses_the_declared_columns(tmp_path) -> None:
    path = write_labels(tmp_path, [{"index": 1, "step_id": "s1"}])
    assert path.read_text(encoding="utf-8").splitlines()[0] == ",".join(PROCEDURE_FIELDS)


def _write_json(payload: dict):
    import tempfile
    from pathlib import Path

    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    return Path(handle.name)


@pytest.mark.parametrize("classes", [set(), {"bottle"}, {"red_box", "target_area"}])
def test_only_matching_frames_are_labelled(classes) -> None:
    """sanity: a frame is labelled only when its objects satisfy a step."""
    steps = [STEP]
    expected = "PICK" if {"red_box"}.issubset(classes) else NO_STEP
    assert (step_for_classes(steps, classes) is not None) == (expected == "PICK")

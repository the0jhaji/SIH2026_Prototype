"""Pure tests for the annotation pipeline. No camera, no network, no training.

    .\\.venv\\Scripts\\python.exe -m pytest experiment\\yolo_training\\tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
for p in (str(REPO_ROOT), str(HERE.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import experiment_tool as et  # noqa: E402


@pytest.fixture()
def ds(tmp_path, monkeypatch):
    """A tiny dataset in a temp dir, with the module's paths pointed at it."""
    import shutil

    for name in (
        "IMAGES_DIR", "LABELS_DIR", "METADATA_DIR", "PROPOSALS_DIR",
        "SAMPLING_DIR", "QA_DIR", "INDEX_FILE", "REPORT_FILE", "DATASET_DIR",
    ):
        monkeypatch.setattr(et, name, tmp_path / Path(getattr(et, name)).name)
    monkeypatch.setattr(et, "CLASSES_FILE", tmp_path / "classes.json")
    # the vocabulary is the real, locked one: the tests must not invent classes
    shutil.copy(et.REPO_ROOT / "dataset" / "experiment_detection" / "classes.json",
                tmp_path / "classes.json")
    et.ensure_layout()
    return tmp_path


# --------------------------------------------------------------- vocabulary
def test_vocabulary_is_the_locked_six():
    vocab = et.load_vocabulary()
    assert vocab.classes == (
        "person", "main_experiment_box", "red_box",
        "yellow_box", "red_target_area", "yellow_target_area",
    )
    assert vocab.n == 6


def test_action_and_state_classes_are_not_detector_classes():
    """Section 5: a single frame cannot prove a held/place action."""
    vocab = et.load_vocabulary()
    for banned in ("opened_box", "held_red_box", "held_yellow_box",
                   "PICK_RED", "PLACE_RED", "held", "placed"):
        assert banned not in vocab.classes


def test_only_person_and_colour_boxes_are_proposable():
    """Section 6: no geometric guess for the container or the target areas."""
    assert set(et.PROPOSABLE) == {"person", "red_box", "yellow_box"}
    assert set(et.MANUAL_ONLY) == {
        "main_experiment_box", "red_target_area", "yellow_target_area"
    }
    assert not set(et.PROPOSABLE) & set(et.MANUAL_ONLY)


def test_vocabulary_rejects_unknown_class(ds):
    vocab = et.load_vocabulary()
    assert vocab.id_of("person") == 0
    assert vocab.id_of("nope") is None
    with pytest.raises(ValueError):
        vocab.index("nope")
    with pytest.raises(ValueError):
        vocab.name_of(99)


# ---------------------------------------------------------------- sampling
def test_sample_frames_covers_beginning_middle_and_end():
    session = {"frames": [{"frame_id": i} for i in range(1, 101)]}
    ids = et.sample_frames(session, head=3, tail=3, uniform=5, budget=0)
    assert ids[0] == 1 and ids[-1] == 100
    assert 50 in ids
    assert ids == sorted(set(ids))


def test_sample_frames_respects_budget_and_keeps_the_ends():
    session = {"frames": [{"frame_id": i} for i in range(1, 200)]}
    ids = et.sample_frames(session, budget=10)
    assert len(ids) <= 10
    assert ids[0] == 1 and ids[-1] == 199


def test_sampling_never_labels_anything(ds):
    """Sampling picks what to look at; only a human save writes a label.

    Runs against the temp fixture, not the real dataset: asserting "no labels
    exist" in the live tree would fail the moment a human annotates anything.
    """
    session = {"frames": [{"frame_id": i} for i in range(1, 51)]}
    et.build_selection({"sessions": [dict(session, session_id="s1", frames=session["frames"])]})
    assert not list(et.LABELS_DIR.rglob("*.txt"))
    assert not list(et.METADATA_DIR.rglob("*.json"))


# ----------------------------------------------------------------- proposals
def test_proposals_are_stored_outside_the_label_tree(ds):
    et.save_proposals("s1", 7, [{"class": "person", "bbox": [1, 2, 3, 4]}])
    assert et.load_proposals("s1", 7)[0]["class"] == "person"
    assert not list(et.LABELS_DIR.rglob("*.txt"))
    assert (et.PROPOSALS_DIR / "s1" / "frame_000007.json").is_file()


def test_proposals_are_not_ground_truth_even_when_the_only_things_there(ds):
    index = _index_one()
    et.save_proposals("s1", 5, [{"class": "person", "bbox": [0, 0, 10, 10]}])
    assert et.label_rows(index) == []
    report = et.dataset_report(index)
    assert report["proposed_objects"]["person"] == 1
    assert report["annotated_frames"] == 0


# ------------------------------------------------------------------ labels
def _index_one():
    return {
        "schema": "astra-experiment-index/1",
        "totals": {"sessions": 1, "frames": 1, "activity_sessions": 0},
        "sessions": [
            {
                "session_id": "s1", "kind": "raw", "label": "box_experiment",
                "activity": None, "path": "dataset/raw/box_experiment/s1", "n_frames": 1,
                "frames": [
                    {"session_id": "s1", "frame_id": 5, "filename": "frame_000005.jpg",
                     "source": "dataset/raw/box_experiment/s1/frame_000005.jpg", "activity": None}
                ],
            }
        ],
    }


def test_save_writes_yolo_text_and_metadata_with_provenance(ds):
    et.save_annotations(
        "s1", 5,
        [{"class": "person", "bbox": [100, 50, 200, 400]}],
        source="dataset/raw/box_experiment/s1/frame_000005.jpg",
        image_size=(1280, 720),
    )
    text = et.label_path("s1", 5).read_text(encoding="utf-8").strip()
    cid, cx, cy, w, h = text.split()
    assert cid == "0"
    assert abs(float(cx) - 0.15625) < 1e-4  # (100+100)/1280
    assert abs(float(cy) - 0.347222) < 1e-4  # (50+200)/720
    assert abs(float(w) - 0.15625) < 1e-4
    meta = et.load_metadata("s1")["frames"]["5"]
    assert meta["reviewed"] is True and meta["empty"] is False
    assert meta["source"].endswith("frame_000005.jpg")


def test_label_rows_ignores_unreviewed_frames(ds):
    et.save_annotations("s1", 5, [{"class": "red_box", "bbox": [0, 0, 50, 50]}],
                        source="x/frame_000005.jpg", image_size=(1280, 720), reviewed=False)
    assert et.label_rows(_index_one()) == []


def test_label_rows_include_reviewed_frames_with_activity(ds):
    index = _index_one()
    et.save_annotations("s1", 5, [{"class": "red_box", "bbox": [10, 10, 40, 40]}],
                        source="x/frame_000005.jpg", activity="PICK_RED", image_size=(1280, 720))
    rows = et.label_rows(index)
    assert len(rows) == 1
    assert rows[0]["session_id"] == "s1" and rows[0]["activity"] == "PICK_RED"
    assert rows[0]["n_boxes"] == 1


def test_background_frame_is_marked_empty_not_missing(ds):
    et.save_annotations("s1", 5, [], source="x/frame_000005.jpg", image_size=(1280, 720))
    rows = et.label_rows(_index_one())
    assert len(rows) == 1 and rows[0]["empty"] is True
    assert et.label_path("s1", 5).read_text(encoding="utf-8") == ""


def test_annotations_are_clipped_to_the_image(ds):
    et.save_annotations("s1", 5, [{"class": "yellow_box", "bbox": [1200, 700, 400, 400]}],
                        source="x/frame_000005.jpg", image_size=(1280, 720))
    text = et.label_path("s1", 5).read_text(encoding="utf-8").strip().split()
    cx, cy, w, h = (float(v) for v in text[1:])
    assert 0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0
    assert cx + w / 2 <= 1.0 + 1e-6 and cy + h / 2 <= 1.0 + 1e-6


def test_unknown_class_is_rejected_before_it_can_be_written(ds):
    with pytest.raises(ValueError):
        et.save_annotations("s1", 5, [{"class": "held_red_box", "bbox": [0, 0, 5, 5]}],
                            source="x/frame_000005.jpg", image_size=(1280, 720))
    assert not et.label_path("s1", 5).exists()


def test_missing_image_size_is_an_error_not_a_guess(ds):
    with pytest.raises(ValueError):
        et.save_annotations("s1", 5, [{"class": "person", "bbox": [0, 0, 5, 5]}],
                            source="x/frame_000005.jpg")


# ------------------------------------------------------------------ layout
def test_layout_has_empty_split_dirs_and_no_split_data(ds):
    et.ensure_layout()
    for split in et.SPLITS:
        assert (et.IMAGES_DIR / split).is_dir() and (et.LABELS_DIR / split).is_dir()
        assert not list((et.LABELS_DIR / split).rglob("*")), "PHASE 3 must not split"


def test_experiment_train_is_never_a_source(tmp_path):
    """The audit showed experiment_train labels are auto-generated, one class
    only and matching no recording. It must not be discovered as a session."""
    root = tmp_path / "repo"
    (root / "dataset" / "raw" / "box_experiment" / "s1").mkdir(parents=True)
    (root / "dataset" / "raw" / "box_experiment" / "s1" / "frame_000001.jpg").write_bytes(b"x")
    (root / "dataset" / "raw" / "box_experiment" / "s1" / "manifest.csv").write_text("a,b\n")
    (root / "dataset" / "experiment_train" / "train").mkdir(parents=True)
    (root / "dataset" / "experiment_train" / "train" / "x.jpg").write_bytes(b"x")
    (root / "dataset" / "experiment_train" / "train" / "x.txt").write_text("0 0.5 0.5 0.2 0.2")
    sessions = et.discover_sessions(root)
    assert [s.session_id for s in sessions] == ["s1"]


def test_activity_sessions_keep_their_activity_label(tmp_path):
    root = tmp_path / "repo"
    d = root / "dataset" / "activity" / "PICK_RED" / "s9"
    d.mkdir(parents=True)
    (d / "frame_000007.jpg").write_bytes(b"x")
    (d / "manifest.csv").write_text("a,b\n")
    sessions = et.discover_sessions(root)
    assert sessions[0].activity == "PICK_RED"
    assert sessions[0].label == "PICK_RED"


def test_index_totals_match_the_sessions(tmp_path):
    root = tmp_path / "repo"
    for label, n in (("box_experiment", 3), ("pick_red_box", 2)):
        d = root / "dataset" / "raw" / label / f"s_{label}"
        d.mkdir(parents=True)
        for i in range(1, n + 1):
            (d / f"frame_{i:06d}.jpg").write_bytes(b"x")
        (d / "manifest.csv").write_text("a,b\n")
    index = et.build_index(root)
    assert index["totals"]["sessions"] == 2
    assert index["totals"]["frames"] == 5

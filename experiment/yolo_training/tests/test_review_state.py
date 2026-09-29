"""Review-state regression tests.

The bug these guard: the UI re-derived the "reviewed" checkbox from the server on
every frame load, so a session of real labels could be stored with
``reviewed=false`` and then rejected by the validator with "label exists but the
frame was never marked reviewed" while ``objects_per_class`` stayed at zero.

    .\\.venv\\Scripts\\python.exe -m pytest experiment\\yolo_training\\tests -q
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
for p in (str(REPO_ROOT), str(HERE.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import annotate as ann  # noqa: E402
import experiment_tool as et  # noqa: E402
from validate_annotations import validate  # noqa: E402

BOX = [{"class": "person", "bbox": [100.0, 50.0, 200.0, 400.0]}]


def _index_two_sessions() -> dict:
    """Two sessions that both contain frame_000074.txt."""
    sessions = []
    for sid, source in (
        ("s_one", "dataset/raw/box_experiment/s_one/frame_000074.jpg"),
        ("s_two", "dataset/raw/pick_red_box/s_two/frame_000074.jpg"),
    ):
        sessions.append(
            {
                "session_id": sid, "kind": "raw", "label": "l", "activity": None,
                "path": f"dataset/raw/{sid}", "n_frames": 1,
                "frames": [
                    {"session_id": sid, "frame_id": 74, "filename": "frame_000074.jpg",
                     "source": source, "activity": None}
                ],
            }
        )
    return {
        "schema": "astra-experiment-index/1",
        "totals": {"sessions": 2, "frames": 2, "activity_sessions": 0},
        "sessions": sessions,
    }


@pytest.fixture()
def store(tmp_path, monkeypatch):
    for name in ("IMAGES_DIR", "LABELS_DIR", "METADATA_DIR", "PROPOSALS_DIR", "SAMPLING_DIR",
                 "QA_DIR", "INDEX_FILE", "REPORT_FILE", "DATASET_DIR", "CLASSES_FILE"):
        monkeypatch.setattr(et, name, tmp_path / Path(getattr(et, name)).name)
    shutil.copy(REPO_ROOT / "dataset" / "experiment_detection" / "classes.json", et.CLASSES_FILE)
    et.ensure_layout()
    monkeypatch.setattr(et, "REPO_ROOT", REPO_ROOT)
    return tmp_path


@pytest.fixture()
def client(store, monkeypatch):
    """The API wired to the real recordings, with the dataset in a temp dir."""
    index = et.build_index(REPO_ROOT)
    monkeypatch.setattr(ann, "INDEX", index)
    monkeypatch.setattr(ann, "_image_size", lambda session_id: (1280, 720))
    with TestClient(ann.app) as c:
        yield c


def _first_session() -> str:
    return ann.INDEX["sessions"][0]["session_id"]


# 1. save an annotation with reviewed=true
def test_save_with_reviewed_true_is_persisted(client):
    sid = _first_session()
    r = client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": True, "image_size": [1280, 720],
        "boxes": BOX,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["reviewed"] is True, "the response must report the stored review state"
    assert body["key"] == f"{sid}/000005"
    on_disk = json.loads(et.metadata_path(sid).read_text(encoding="utf-8"))
    assert on_disk["frames"]["5"]["reviewed"] is True


# 2. reload the annotation and verify reviewed=true
def test_reopening_the_frame_reports_reviewed_true(client):
    sid = _first_session()
    client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": True, "image_size": [1280, 720], "boxes": BOX,
    })
    # a fresh page load asks the server, not local state
    detail = client.get(f"/api/frame/{sid}/5").json()
    assert detail["reviewed"] is True
    assert detail["annotations"][0]["class"] == "person"
    assert et.annotation_state(sid, 5)["reviewed"] is True


def test_review_can_be_set_without_resending_boxes(client):
    """The tick is its own durable action, so nothing has to be redrawn."""
    sid = _first_session()
    client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": False, "image_size": [1280, 720], "boxes": BOX,
    })
    assert et.annotation_state(sid, 5)["reviewed"] is False
    r = client.post("/api/review", json={"session_id": sid, "frame_id": 5, "reviewed": True})
    assert r.status_code == 200 and r.json()["reviewed"] is True
    assert et.annotation_state(sid, 5)["reviewed"] is True
    # the boxes drawn earlier are still there
    assert et.label_path(sid, 5).read_text(encoding="utf-8").strip() != ""
    assert client.get(f"/api/frame/{sid}/5").json()["annotations"][0]["class"] == "person"


# 3. label exists + reviewed=true => counted as confirmed
def test_reviewed_label_is_counted_as_confirmed(client, monkeypatch):
    sid = _first_session()
    client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": True, "image_size": [1280, 720], "boxes": BOX,
    })
    monkeypatch.setattr("validate_annotations.build_index", lambda: ann.INDEX)
    monkeypatch.setattr("validate_annotations.save_index", lambda index: None)
    errors, _warnings, report = validate()
    assert report["annotated_frames"] == 1
    assert report["objects_per_class"]["person"] == 1
    assert not [e for e in errors if "never marked reviewed" in e]
    assert et.label_rows(ann.INDEX)[0]["key"] == f"{sid}/000005"


# 4. label exists + reviewed=false => rejected by strict validation
def test_unreviewed_label_is_rejected_and_excluded(client, monkeypatch):
    sid = _first_session()
    client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": False, "image_size": [1280, 720], "boxes": BOX,
    })
    monkeypatch.setattr("validate_annotations.build_index", lambda: ann.INDEX)
    monkeypatch.setattr("validate_annotations.save_index", lambda index: None)
    errors, _warnings, report = validate()
    assert any("never marked reviewed" in e for e in errors)
    assert any(sid in e for e in errors), "the error must name the session, not just the file"
    assert report["annotated_frames"] == 0
    assert report["objects_per_class"]["person"] == 0
    assert et.label_rows(ann.INDEX) == [], "unreviewed labels must stay out of training"


def test_backfill_recovers_labels_without_touching_the_boxes(client, monkeypatch):
    """The recovery path for a session whose review flags were lost."""
    sid = _first_session()
    client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": False, "image_size": [1280, 720], "boxes": BOX,
    })
    before = et.label_path(sid, 5).read_text(encoding="utf-8")
    stranded = et.unreviewed_label_frames(ann.INDEX)
    assert [s["key"] for s in stranded] == [f"{sid}/000005"]
    promoted = et.backfill_reviewed(ann.INDEX)
    assert len(promoted) == 1
    assert et.annotation_state(sid, 5)["reviewed"] is True
    assert et.label_path(sid, 5).read_text(encoding="utf-8") == before, "labels must be untouched"
    assert et.unreviewed_label_frames(ann.INDEX) == []
    assert len(et.label_rows(ann.INDEX)) == 1


def test_backfill_never_invents_an_annotation(store):
    """No label file means nothing to promote: backfill must stay silent."""
    index = _index_two_sessions()
    assert et.unreviewed_label_frames(index) == []
    assert et.backfill_reviewed(index) == []


# 5. same frame filename in different sessions must not collide
def test_same_frame_filename_in_two_sessions_does_not_collide(client, monkeypatch):
    index = _index_two_sessions()
    monkeypatch.setattr(ann, "INDEX", index)
    sid_a, sid_b = "s_one", "s_two"
    client.post("/api/save", json={
        "session_id": sid_a, "frame_id": 74, "reviewed": True,
        "image_size": [1280, 720], "boxes": BOX,
    })
    client.post("/api/save", json={
        "session_id": sid_b, "frame_id": 74, "reviewed": False,
        "image_size": [1280, 720],
        "boxes": [{"class": "red_box", "bbox": [10.0, 10.0, 40.0, 40.0]}],
    })
    # both files exist and are named identically, in different directories
    a_file = et.label_path(sid_a, 74)
    b_file = et.label_path(sid_b, 74)
    assert a_file.name == b_file.name == "frame_000074.txt"
    assert a_file.parent != b_file.parent
    assert a_file.read_text(encoding="utf-8").startswith("0 ")
    assert b_file.read_text(encoding="utf-8").startswith("2 ")

    # the flags are independent: reviewing one must not review the other
    assert et.annotation_state(sid_a, 74)["reviewed"] is True
    assert et.annotation_state(sid_b, 74)["reviewed"] is False
    assert et.annotation_state(sid_a, 74)["key"] != et.annotation_state(sid_b, 74)["key"]

    # and only the reviewed one is a training row
    rows = et.label_rows(index)
    assert [r["key"] for r in rows] == [f"{sid_a}/000074"]


def test_frame_key_is_scoped_to_session_and_frame():
    assert et.frame_key("s_a", 74) == "s_a/000074"
    assert et.frame_key("s_b", 74) == "s_b/000074"
    assert et.frame_key("s_a", 74) != et.frame_key("s_b", 74)
    assert et.frame_key("s_a", 4) != et.frame_key("s_a", 74)


def test_duplicate_frame_ids_in_one_session_are_rejected(tmp_path):
    """Two files claiming the same frame id would overwrite each other's labels."""
    root = tmp_path / "repo"
    d = root / "dataset" / "raw" / "box_experiment" / "s1"
    d.mkdir(parents=True)
    (d / "frame_000005.jpg").write_bytes(b"x")
    (d / "frame_5.png").write_bytes(b"x")  # same number, different extension
    (d / "manifest.csv").write_text("a,b\n")
    with pytest.raises(ValueError, match="must be unique"):
        et.discover_sessions(root)


def test_reopening_a_frame_after_unticking_shows_unchecked(client):
    sid = _first_session()
    client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": True, "image_size": [1280, 720], "boxes": BOX,
    })
    client.post("/api/review", json={"session_id": sid, "frame_id": 5, "reviewed": False})
    assert client.get(f"/api/frame/{sid}/5").json()["reviewed"] is False


def test_session_progress_counts_reviewed_frames(client):
    sid = _first_session()
    client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": True, "image_size": [1280, 720], "boxes": BOX,
    })
    row = next(s for s in client.get("/api/sessions").json()["sessions"] if s["session_id"] == sid)
    assert row["n_reviewed"] == 1
    assert row["n_annotated"] == 1
    assert row["frame_ids"], "the UI needs the real id list to navigate without assuming +/-1"

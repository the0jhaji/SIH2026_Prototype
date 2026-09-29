"""API-level tests for the annotation tool. No server, no camera, no training."""

from __future__ import annotations

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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    for name in ("IMAGES_DIR", "LABELS_DIR", "METADATA_DIR", "PROPOSALS_DIR", "SAMPLING_DIR",
                 "QA_DIR", "INDEX_FILE", "REPORT_FILE", "DATASET_DIR", "CLASSES_FILE"):
        monkeypatch.setattr(et, name, tmp_path / Path(getattr(et, name)).name)
    import shutil
    shutil.copy(REPO_ROOT / "dataset" / "experiment_detection" / "classes.json", et.CLASSES_FILE)
    et.ensure_layout()
    monkeypatch.setattr(ann, "INDEX", et.build_index())
    monkeypatch.setattr(ann, "_image_size", lambda session_id: (1280, 720))
    with TestClient(ann.app) as c:
        yield c


def test_page_serves_a_canvas_ui(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<canvas" in r.text
    assert "keydown" in r.text  # the keyboard shortcuts the tool promises


def test_config_exposes_the_locked_vocabulary(client):
    classes = client.get("/api/config").json()["classes"]
    assert [c["name"] for c in classes] == [
        "person", "main_experiment_box", "red_box", "yellow_box",
        "red_target_area", "yellow_target_area",
    ]
    proposable = {c["name"] for c in classes if c["proposable"]}
    assert proposable == {"person", "red_box", "yellow_box"}


def test_frame_detail_returns_proposals_separately_from_annotations(client):
    sid = ann.INDEX["sessions"][0]["session_id"]
    et.save_proposals(sid, 5, [{"class": "person", "bbox": [0, 0, 10, 10]}])
    body = client.get(f"/api/frame/{sid}/5").json()
    assert len(body["proposals"]) == 1
    assert body["annotations"] == []
    assert body["reviewed"] is False


def test_save_writes_labels_and_provenance(client):
    sid = ann.INDEX["sessions"][0]["session_id"]
    r = client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": True, "image_size": [1280, 720],
        "boxes": [{"class": "person", "bbox": [100, 50, 200, 400]},
                  {"class": "red_box", "bbox": [400, 300, 60, 60]}],
    })
    assert r.status_code == 200 and r.json()["ok"] is True
    assert et.label_path(sid, 5).is_file()
    rows = et.label_rows(ann.INDEX)
    assert len(rows) == 1 and rows[0]["n_boxes"] == 2
    assert rows[0]["source"].endswith(".jpg")


def test_save_rejects_a_class_that_is_not_in_the_vocabulary(client):
    """A held/place state must not be smuggled in as a detector class."""
    sid = ann.INDEX["sessions"][0]["session_id"]
    with TestClient(ann.app, raise_server_exceptions=False) as c:
        r = c.post("/api/save", json={
            "session_id": sid, "frame_id": 5, "reviewed": True, "image_size": [1280, 720],
            "boxes": [{"class": "held_red_box", "bbox": [0, 0, 10, 10]}],
        })
    assert r.status_code >= 400
    assert not et.label_path(sid, 5).exists()


def test_saving_an_empty_frame_marks_it_background_not_unlabelled(client):
    sid = ann.INDEX["sessions"][0]["session_id"]
    client.post("/api/save", json={
        "session_id": sid, "frame_id": 5, "reviewed": True, "image_size": [1280, 720], "boxes": [],
    })
    rows = et.label_rows(ann.INDEX)
    assert len(rows) == 1 and rows[0]["empty"] is True
    assert et.label_path(sid, 5).read_text(encoding="utf-8") == ""


def test_next_unreviewed_skips_frames_a_human_already_saved(client):
    sid = ann.INDEX["sessions"][0]["session_id"]
    first = client.get(f"/api/next/{sid}").json()
    client.post("/api/save", json={
        "session_id": sid, "frame_id": first["frame_id"], "reviewed": True,
        "image_size": [1280, 720], "boxes": [],
    })
    after = client.get(f"/api/next/{sid}").json()
    assert after["frame_id"] > first["frame_id"]


def test_stats_report_zero_before_any_human_work(client):
    stats = client.get("/api/stats").json()
    assert stats["annotated_frames"] == 0
    assert all(n == 0 for n in stats["objects_per_class"].values())

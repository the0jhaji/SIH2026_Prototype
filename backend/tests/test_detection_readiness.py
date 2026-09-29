"""Can the loaded model actually see the experiment vocabulary?

Guards the honesty contract of the Experiment Demo. The failure this prevents:
a generic COCO YOLO running correctly, finding `person` and a `book`, while the
dashboard shows the COCO boxes in the "experiment objects" panel and the
operator concludes the camera or the threshold is broken. It is neither — no
shipped model knows the six experiment classes, and the UI has to say so.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.detection_readiness import (  # noqa: E402
    NOT_READY_LABEL,
    READY_LABEL,
    class_counts,
    load_experiment_classes,
    model_readiness,
    partition_detections,
)

VOCAB = [
    "person",
    "main_experiment_box",
    "red_box",
    "yellow_box",
    "red_target_area",
    "yellow_target_area",
]


def test_canonical_vocabulary_is_six_classes_from_the_contract_file():
    assert load_experiment_classes() == VOCAB


def test_no_model_at_all_is_not_ready_and_never_claims_ready():
    r = model_readiness(None)
    assert r["ready"] is False
    assert r["label"] == NOT_READY_LABEL
    assert r["missing"] == VOCAB


def test_not_ready_label_is_exact():
    assert NOT_READY_LABEL == "EXPERIMENT MODEL: NOT TRAINED / NOT READY"
    assert READY_LABEL == "EXPERIMENT MODEL: READY"


def test_full_coverage_is_ready():
    r = model_readiness(VOCAB)
    assert r["ready"] is True
    assert r["label"] == READY_LABEL
    assert r["missing"] == []


def test_shipped_yolov8n_cannot_cover_the_experiment_vocabulary():
    """Read the real shipped class list: its only overlap is `person`."""
    names_file = Path(__file__).resolve().parents[2] / "models" / "detection" / "yolov8n.names"
    if not names_file.exists():
        pytest.skip("yolov8n.names not installed")
    classes = [l.strip() for l in names_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(classes) == 80
    r = model_readiness(classes)
    assert r["ready"] is False
    assert r["label"] == NOT_READY_LABEL
    assert r["supported"] == ["person"]
    assert set(r["missing"]) == set(VOCAB) - {"person"}
    # 80 classes, so it is a general-purpose head, not a narrow specialist.
    assert r["narrow"] is False


def test_short_class_list_is_narrow_not_general():
    """A 3-class head is a specialist whatever it is named."""
    r = model_readiness(["person", "book", "cup"])
    assert r["ready"] is False
    assert r["narrow"] is True


def test_two_class_custom_model_is_narrow_and_not_ready():
    r = model_readiness(["red_box", "yellow_box"])
    assert r["ready"] is False
    assert r["narrow"] is True
    assert r["supported"] == ["red_box", "yellow_box"]
    assert set(r["missing"]) == {
        "person",
        "main_experiment_box",
        "red_target_area",
        "yellow_target_area",
    }


def test_partial_coverage_is_not_ready():
    r = model_readiness(["person", "red_box", "yellow_box"])
    assert r["ready"] is False
    assert r["narrow"] is True
    assert r["missing"] == [
        "main_experiment_box",
        "red_target_area",
        "yellow_target_area",
    ]


def test_coco_book_is_never_an_experiment_object():
    dets = [
        {"class_name": "book", "confidence": 0.9},
        {"class_name": "person", "confidence": 0.95},
        {"class_name": "red_box", "confidence": 0.7},
    ]
    split = partition_detections(dets)
    assert [d["class_name"] for d in split["experiment"]] == ["person", "red_box"]
    assert [d["class_name"] for d in split["generic"]] == ["book"]
    assert "book" not in [d["class_name"] for d in split["experiment"]]


def test_unknown_object_never_counts_as_experiment_or_generic():
    dets = [{"class_name": "unknown_object", "confidence": 0.5}]
    split = partition_detections(dets)
    assert split["experiment"] == []
    assert split["generic"] == []
    assert len(split["unknown"]) == 1


def test_partition_preserves_every_detection_exactly_once():
    dets = [
        {"class_name": "book"},
        {"class_name": "person"},
        {"class_name": "unknown_object"},
        {"class_name": "yellow_box"},
        {"class_name": "laptop"},
    ]
    split = partition_detections(dets)
    total = sum(len(v) for v in split.values())
    assert total == len(dets)
    ids = [d["class_name"] for v in split.values() for d in v]
    assert sorted(ids) == sorted(d["class_name"] for d in dets)


def test_class_counts_reports_per_class_totals():
    dets = [
        {"class_name": "person"},
        {"class_name": "person"},
        {"class_name": "book"},
    ]
    assert class_counts(dets) == {"book": 1, "person": 2}


def test_class_counts_ignores_unnamed_entries():
    assert class_counts([{"confidence": 0.5}, {"class_name": ""}]) == {}


def test_empty_detections_yield_empty_everything():
    split = partition_detections([])
    assert split == {"experiment": [], "generic": [], "unknown": []}
    assert class_counts([]) == {}
    # And a healthy model that simply sees nothing is still "ready".
    assert model_readiness(VOCAB)["ready"] is True


def test_readiness_survives_a_missing_contract_file(monkeypatch):
    """A missing vocabulary must degrade to 'unknown', never invent classes."""
    import app.detection_readiness as dr

    monkeypatch.setattr(dr, "_cached", None)
    monkeypatch.setattr(
        dr, "EXPERIMENT_CLASSES_FILE", Path("does-not-exist/classes.json")
    )
    assert dr.load_experiment_classes() == []
    r = dr.model_readiness(["person", "book"])
    assert r["ready"] is False
    assert r["required"] == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

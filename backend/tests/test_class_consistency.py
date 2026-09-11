"""Class-ID consistency across every consumer of the detection vocabulary.

classes.json, the annotator's DEFAULT_CLASSES, the hazard KB, the inference
run-time `.names` file, and the frontend's CLASS_COLOR palette must all agree
on the set of trained classes — a drift between any two of them would silently
mislabel detections or mis-map hazards. This test is the guard rail.

Note on the experiment: the legacy box-demo object table (experiment.json) uses
its own 5-class scene scheme, so it is intentionally excluded here.
"""

import json
import re
from pathlib import Path

from app.safety.hazards import load_hazards

REPO_ROOT = Path(__file__).resolve().parents[2]
CLASSES_PATH = REPO_ROOT / "dataset" / "annotation" / "classes.json"
DETECTION_TS = REPO_ROOT / "frontend" / "src" / "domain" / "detection.ts"
DEFAULT_MODEL = REPO_ROOT / "models" / "detection" / "yolov8n.onnx"
DEFAULT_NAMES = DEFAULT_MODEL.with_suffix(".names")

EXPECTED_CLASSES = [
    "person",
    "knife",
    "pen",
    "red_box",
    "yellow_box",
    "floating_tool",
    "loose_cable",
    "bottle",
]


def _dataset_classes() -> list[str]:
    raw = json.loads(CLASSES_PATH.read_text(encoding="utf-8"))
    classes = [c["id"] if isinstance(c, dict) else c for c in raw["classes"]]
    return classes


def _annotator_default_classes() -> list[str]:
    import sys

    sys.path.insert(0, str(REPO_ROOT / "dataset"))
    from annotation.annotator import DEFAULT_CLASSES

    return list(DEFAULT_CLASSES)


def test_classes_json_matches_canonical_vocabulary() -> None:
    assert _dataset_classes() == EXPECTED_CLASSES


def test_annotator_default_classes_match_classes_json() -> None:
    assert _annotator_default_classes() == EXPECTED_CLASSES


def test_hazard_kb_covers_every_trained_class() -> None:
    kb = load_hazards()
    mapped = set(EXPECTED_CLASSES) & set(kb.classes)
    assert mapped == set(EXPECTED_CLASSES), f"KB missing: {sorted(set(EXPECTED_CLASSES) - mapped)}"
    for name in EXPECTED_CLASSES:
        assert kb.spec_for(name) is not None


def test_frontend_color_palette_covers_trained_classes() -> None:
    text = DETECTION_TS.read_text(encoding="utf-8")
    block = text.split("CLASS_COLOR", 1)[1]
    for name in EXPECTED_CLASSES + ["unknown_object"]:
        assert re.search(rf"{name}\s*:", block), f"CLASS_COLOR missing {name!r}"


def test_ai_detector_classes_stay_in_canonical_vocabulary() -> None:
    """Every AI detector only emits a subset of the trained vocabulary — none
    may invent a 9th trained class. unknown_object stays a separate proposal
    category, never inside the 0..7 YOLO id space."""
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from ai.detection.generic import GenericProposalDetector
    from ai.detection.heuristic_detector import ColorMotionDetector
    from ai.detection.mock_detector import MockDetector

    assert set(ColorMotionDetector().status().classes) <= set(EXPECTED_CLASSES)
    for scene in ("bas", "space_station", "safety_sequence", "empty"):
        classes = MockDetector(scene=scene).status().classes
        assert set(classes) <= set(EXPECTED_CLASSES), f"mock scene {scene!r} leaks classes"
    generic = GenericProposalDetector().status().classes
    assert set(generic).isdisjoint(EXPECTED_CLASSES)
    assert "unknown_object" not in EXPECTED_CLASSES


def test_runtime_names_file_is_either_coco_generic_or_trained_contract() -> None:
    """The `.names` next to the ONNX drives inference classes.

    A generic COCO model (80 classes) honestly runs the generic runtime; a
    trained 8-class model's .names must exactly match the training vocabulary.
    """
    names = DEFAULT_NAMES.read_text(encoding="utf-8").splitlines() if DEFAULT_NAMES.exists() else []
    if len(names) == 80:
        return  # stock COCO model — generic runtime, honestly reported
    assert names == EXPECTED_CLASSES, "trained .names drift from classes.json"
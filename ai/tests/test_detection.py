"""Tests for the ai/detection layer (interface, mock, yolo, types)."""

import numpy as np
import pytest

from detection import dual_yolo
from detection.detector import create_detector
from detection.mock_detector import MockDetector
from detection.types import Detection
from detection.yolo_detector import YoloDetector

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def test_detection_structure_and_to_dict() -> None:
    d = Detection("person", 0.95, 10, 20, 110, 340, 1234)
    assert d.width == 100
    assert d.height == 320
    payload = d.to_dict()
    assert set(payload) == {"class_name", "confidence", "x1", "y1", "x2", "y2", "timestamp"}
    assert payload == {
        "class_name": "person",
        "confidence": 0.95,
        "x1": 10,
        "y1": 20,
        "x2": 110,
        "y2": 340,
        "timestamp": 1234,
    }


def test_mock_emits_deterministic_classes_and_confidences() -> None:
    d1 = MockDetector().detect(FRAME)
    d2 = MockDetector().detect(FRAME)
    expected = [("person", 0.95), ("red_box", 0.91), ("yellow_box", 0.89)]
    assert [(d.class_name, d.confidence) for d in d1] == expected
    assert [(d.class_name, d.confidence) for d in d2] == expected


def test_mock_boxes_inside_frame() -> None:
    h, w = FRAME.shape[:2]
    for d in MockDetector().detect(FRAME):
        assert 0 <= d.x1 < d.x2 <= w
        assert 0 <= d.y1 < d.y2 <= h


def test_mock_boxes_scale_with_frame_size() -> None:
    small = [d for d in MockDetector().detect(np.zeros((240, 320, 3), np.uint8)) if d.class_name == "person"][0]
    big = [d for d in MockDetector().detect(FRAME) if d.class_name == "person"][0]
    assert big.x2 > small.x2
    assert big.y2 > small.y2


def test_mock_empty_scene_produces_no_detections() -> None:
    assert MockDetector(scene="empty").detect(FRAME) == []


def test_mock_status() -> None:
    st = MockDetector().status()
    assert st.detector_type == "mock"
    assert st.model_loaded is True


def test_factory_builds_mock() -> None:
    assert create_detector("mock").name == "mock"


def test_factory_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="Unknown detector kind"):
        create_detector("nope")


def test_factory_dual_passes_independent_model_paths(monkeypatch) -> None:
    calls: list[dict] = []

    class SpyYolo:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(dual_yolo, "YoloDetector", SpyYolo)
    create_detector(
        "dual",
        general_model_path="general.onnx",
        custom_model_path="custom.onnx",
        conf_threshold=0.4,
        cv_threads=2,
    )

    assert [call["model_path"] for call in calls] == ["general.onnx", "custom.onnx"]
    assert all(call["conf_threshold"] == 0.4 for call in calls)
    assert all(call["cv_threads"] == 2 for call in calls)


def test_factory_dual_keeps_independent_defaults(monkeypatch) -> None:
    calls: list[dict] = []

    class SpyYolo:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(dual_yolo, "YoloDetector", SpyYolo)
    create_detector("dual", model_path="single-backend.onnx")

    assert [call["model_path"] for call in calls] == [
        "detection/yolov8n.onnx",
        "detection/experiment_custom.onnx",
    ]


def test_yolo_missing_model_raises_clear_error() -> None:
    det = YoloDetector(model_path="definitely_missing_model.onnx")
    assert det.is_loaded is False
    with pytest.raises(FileNotFoundError, match="not found"):
        det.detect(FRAME)
    assert det.is_loaded is False


def test_yolo_status_reports_missing_model() -> None:
    st = YoloDetector(model_path="definitely_missing_model.onnx").status()
    assert st.detector_type == "yolo"
    assert st.model_loaded is False
    assert st.model_path.endswith("definitely_missing_model.onnx")


def test_yolo_default_classes_match_bas_scene() -> None:
    assert list(YoloDetector().classes) == [
        "person",
        "experiment_box",
        "red_box",
        "yellow_box",
        "target_area",
    ]
import json

import numpy as np

from pipeline.detections import Box, ObjectDetection


def test_box_tuple_and_center() -> None:
    box = Box(x=10, y=20, width=40, height=30)
    assert box.as_tuple() == (10, 20, 40, 30)
    assert box.cx == 30.0
    assert box.cy == 35.0


def test_box_clamp_inside() -> None:
    box = Box(x=100, y=100, width=50, height=50)
    assert box.clamp(640, 480) == box


def test_box_clamp_partially_outside() -> None:
    box = Box(x=-20, y=450, width=690, height=120)
    clamped = box.clamp(640, 480)
    assert clamped.x >= 0
    assert clamped.y <= 480
    assert clamped.x + clamped.width <= 640
    assert clamped.y + clamped.height <= 480


def test_object_detection_to_dict_keys() -> None:
    det = ObjectDetection(
        class_name="red_box",
        confidence=0.9346,
        bounding_box=Box(x=412, y=188, width=96, height=74),
        timestamp=1725000000000,
    )
    data = det.to_dict()
    assert set(data) == {"class_name", "confidence", "bounding_box", "timestamp"}
    assert data["class_name"] == "red_box"
    assert data["confidence"] == 0.9346
    assert data["bounding_box"] == [412, 188, 96, 74]
    assert data["timestamp"] == 1725000000000


def test_object_detection_json_serializable() -> None:
    det = ObjectDetection(
        class_name="person",
        confidence=1.0,
        bounding_box=Box(x=0, y=0, width=10, height=20),
        timestamp=1,
    )
    loaded = json.loads(json.dumps(det.to_dict()))
    assert loaded["class_name"] == "person"
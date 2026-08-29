import numpy as np

from pipeline.mock import REQUIRED_CLASSES, MockDetector

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def test_mock_emits_required_classes() -> None:
    dets = MockDetector().detect(FRAME)
    classes = {d.class_name for d in dets}
    assert classes == set(REQUIRED_CLASSES)


def test_mock_boxes_inside_frame() -> None:
    for det in MockDetector().detect(FRAME):
        box = det.bounding_box
        assert 0 <= box.x < 640
        assert 0 <= box.y < 480
        assert box.x + box.width <= 640
        assert box.y + box.height <= 480
        assert box.width > 0 and box.height > 0


def test_mock_confidence_bounds() -> None:
    for det in MockDetector().detect(FRAME):
        assert 0.0 < det.confidence <= 1.0


def test_mock_timestamps_present() -> None:
    for det in MockDetector().detect(FRAME):
        assert det.timestamp > 0


def test_mock_respects_explicit_timestamp() -> None:
    dets = MockDetector().detect(FRAME, timestamp_ms=1234)
    assert all(d.timestamp == 1234 for d in dets)


def test_mock_deterministic_for_same_tick() -> None:
    a = MockDetector(seed=7).detect(FRAME)
    b = MockDetector(seed=7).detect(FRAME)
    sig_a = [(d.class_name, d.confidence, d.bounding_box.as_tuple()) for d in a]
    sig_b = [(d.class_name, d.confidence, d.bounding_box.as_tuple()) for d in b]
    assert sig_a == sig_b


def test_mock_person_moves_over_ticks() -> None:
    d = MockDetector(seed=7)
    x1 = next(x for x in d.detect(FRAME) if x.class_name == "person").bounding_box.x
    x2 = next(x for x in d.detect(FRAME) if x.class_name == "person").bounding_box.x
    assert x1 != x2


def test_mock_adapts_to_frame_size() -> None:
    small = MockDetector().detect(np.zeros((240, 320, 3), dtype=np.uint8))
    for det in small:
        assert det.bounding_box.x + det.bounding_box.width <= 320
        assert det.bounding_box.y + det.bounding_box.height <= 240
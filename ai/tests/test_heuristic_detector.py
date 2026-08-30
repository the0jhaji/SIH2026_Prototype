"""Tests for the local heuristic detector (HSV color blobs + motion).

Deterministic synthetic frames only — a real webcam is never touched.
"""

import numpy as np
import pytest

from detection.detector import create_detector
from detection.heuristic_detector import ColorMotionDetector


def bgr_red_square(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    frame[y1:y2, x1:x2] = (0, 0, 200)


def bgr_yellow_square(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    frame[y1:y2, x1:x2] = (0, 200, 200)


def test_empty_frame_detects_nothing() -> None:
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    assert ColorMotionDetector().detect(frame) == []


def test_single_call_has_no_person() -> None:
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    bgr_red_square(frame, 40, 40, 140, 140)
    dets = ColorMotionDetector().detect(frame)
    assert [d.class_name for d in dets] == ["red_box"]  # no motion memory yet


def test_red_square_detected_as_red_box() -> None:
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    bgr_red_square(frame, 100, 50, 200, 150)
    dets = ColorMotionDetector().detect(frame)
    red = [d for d in dets if d.class_name == "red_box"]
    assert len(red) == 1
    d = red[0]
    assert d.confidence == pytest.approx(0.9)
    assert abs(d.x1 - 100) <= 3 and abs(d.y1 - 50) <= 3
    assert abs(d.x2 - 200) <= 3 and abs(d.y2 - 150) <= 3
    assert 0 <= d.x1 < d.x2 <= 400 and 0 <= d.y1 < d.y2 <= 300


def test_yellow_square_detected_as_yellow_box() -> None:
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    bgr_yellow_square(frame, 120, 60, 220, 170)
    dets = ColorMotionDetector().detect(frame)
    yellow = [d for d in dets if d.class_name == "yellow_box"]
    assert len(yellow) == 1
    assert abs(yellow[0].x1 - 120) <= 3 and abs(yellow[0].x2 - 220) <= 3


def test_red_and_yellow_are_separate() -> None:
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    bgr_red_square(frame, 30, 30, 130, 130)
    bgr_yellow_square(frame, 220, 30, 320, 130)
    classes = sorted(d.class_name for d in ColorMotionDetector().detect(frame))
    assert classes == ["red_box", "yellow_box"]


def test_motion_detects_person() -> None:
    det = ColorMotionDetector()
    a = np.zeros((300, 400, 3), dtype=np.uint8)
    det.detect(a)  # establish background
    b = a.copy()
    b[80:280, 150:260] = (255, 255, 255)  # white foreground, roughly person-sized
    dets = det.detect(b)
    people = [d for d in dets if d.class_name == "person"]
    assert len(people) == 1
    assert people[0].confidence == pytest.approx(0.85)
    assert abs(people[0].x1 - 150) <= 8 and people[0].y1 <= 100
    assert people[0].x2 >= 260 and people[0].y2 >= 280


def test_no_motion_means_no_person() -> None:
    det = ColorMotionDetector()
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    bgr_yellow_square(frame, 40, 40, 160, 160)
    assert det.detect(frame)  # first call learns background, no person
    assert [d.class_name for d in det.detect(frame)] == ["yellow_box"]


def test_tiny_blob_ignored() -> None:
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    bgr_red_square(frame, 10, 10, 15, 15)  # 25 px < 100 px minimum
    assert ColorMotionDetector().detect(frame) == []


def test_confidence_filter_applied() -> None:
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    bgr_red_square(frame, 100, 50, 200, 150)
    dets = ColorMotionDetector(conf_threshold=0.95).detect(frame)
    assert dets == []  # 0.9 < 0.95 threshold


def test_status_reports_heuristic_classes() -> None:
    st = ColorMotionDetector().status()
    assert st.detector_type == "heuristic"
    assert st.model_loaded is True
    assert st.classes == ("person", "red_box", "yellow_box")


def test_factory_builds_heuristic() -> None:
    assert create_detector("heuristic").name == "heuristic"
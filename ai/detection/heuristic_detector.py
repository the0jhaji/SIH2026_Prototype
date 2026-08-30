"""Local heuristic object detector (no model, no weights).

Detects the three things a webcam scene can give you without any training:

- ``person``   — motion (frame-to-frame difference), so a moving astronaut is
                seen and a static empty desk is not;
- ``red_box``  — saturated red blobs (HSV hue ~0/180);
- ``yellow_box`` — saturated yellow blobs (HSV hue ~15–35).

This is the honest no-training detector: on an empty desk it returns nothing.
It never claims to see ``experiment_box`` or ``target_area`` — those genuinely
need a trained model (``yolo_detector.py`` + the Phase 4C pipeline). Boxes are
real, in image space, derived from the pixels — deterministic for synthetic
input, imperfect for real scenes (lighting, skin tones), which the
``heuristic`` name keeps honest.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .detector import BaseDetector
from .types import Detection, DetectorStatus

# HSV ranges (OpenCV: H 0–179, S/V 0–255).
RED_MASKS = [
    (np.array([0, 110, 70], dtype=np.uint8), np.array([10, 255, 255], dtype=np.uint8)),
    (np.array([170, 110, 70], dtype=np.uint8), np.array([180, 255, 255], dtype=np.uint8)),
]
YELLOW_MASK = (np.array([15, 110, 70], dtype=np.uint8), np.array([35, 255, 255], dtype=np.uint8))

KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))


def _blobs(mask: np.ndarray, min_area: int) -> list[tuple[int, int, int, int]]:
    """Bounding rects (x1, y1, x2, y2) of connected regions above ``min_area``."""
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue
        boxes.append((x, y, x + w, y + h))
    return boxes


class ColorMotionDetector(BaseDetector):
    name = "heuristic"
    model_free = True

    def __init__(
        self,
        conf_threshold: float = 0.5,
        min_box_area: float = 0.004,
        min_person_area: float = 0.03,
        motion_threshold: int = 25,
    ) -> None:
        self.conf_threshold = conf_threshold
        self.min_box_area = min_box_area
        self.min_person_area = min_person_area
        self.motion_threshold = motion_threshold
        self._prev_gray: Optional[np.ndarray] = None

    def detect(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[Detection]:
        ts = self._ts(timestamp_ms)
        height, width = frame.shape[:2]
        area = height * width
        dets: list[Detection] = []

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        red_mask = sum(
            cv2.inRange(hsv, lower, upper) for lower, upper in RED_MASKS
        )
        for x1, y1, x2, y2 in _blobs(red_mask, max(100, int(area * self.min_box_area))):
            dets.append(self._mk("red_box", 0.9, x1, y1, x2, y2, width, height, ts))

        yellow_mask = cv2.inRange(hsv, *YELLOW_MASK)
        for x1, y1, x2, y2 in _blobs(yellow_mask, max(100, int(area * self.min_box_area))):
            dets.append(self._mk("yellow_box", 0.9, x1, y1, x2, y2, width, height, ts))

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self._prev_gray is not None:
            diff = cv2.absdiff(gray, self._prev_gray)
            _, motion = cv2.threshold(diff, self.motion_threshold, 255, cv2.THRESH_BINARY)
            motion = cv2.morphologyEx(motion, cv2.MORPH_CLOSE, KERNEL)
            min_person = max(200, int(area * self.min_person_area))
            for x1, y1, x2, y2 in _blobs(motion, min_person):
                dets.append(self._mk("person", 0.85, x1, y1, x2, y2, width, height, ts))
        self._prev_gray = gray

        dets.sort(key=lambda d: d.confidence, reverse=True)
        return [d for d in dets if d.confidence >= self.conf_threshold]

    def _mk(
        self,
        name: str,
        conf: float,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        width: int,
        height: int,
        ts: int,
    ) -> Detection:
        x1, x2 = max(0, min(x1, width)), max(0, min(x2, width))
        y1, y2 = max(0, min(y1, height)), max(0, min(y2, height))
        if x2 <= x1:
            x2 = x1 + 1
        if y2 <= y1:
            y2 = y1 + 1
        return Detection(
            class_name=name,
            confidence=conf,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            timestamp=ts,
        )

    def status(self) -> DetectorStatus:
        return DetectorStatus(
            detector_type=self.name,
            model_loaded=True,
            classes=("person", "red_box", "yellow_box"),
        )
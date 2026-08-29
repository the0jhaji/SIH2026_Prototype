"""Deterministic mock detector.

Emits synthetic ``person`` / ``experiment_box`` / ``red_box`` /
``yellow_box`` / ``target_area`` detections for every frame, in fixed places
with a slowly wandering ``person``. Lets the whole stack — pipeline, preview,
annotation, and the Phase 4 activity mapping — run with no model weights and
no meaningful camera content.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .base import BaseDetector
from .detections import Box, ObjectDetection

#: The five classes the YOLO detector is expected to output (BAS-AI scene).
REQUIRED_CLASSES = ("person", "experiment_box", "red_box", "yellow_box", "target_area")


class MockDetector(BaseDetector):
    name = "mock"
    model_free = True

    def __init__(self, seed: int = 0) -> None:
        self._tick = 0
        self._phase = float(seed)

    def detect(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[ObjectDetection]:
        self._tick += 1
        t = self._tick
        ts = self._ts(timestamp_ms)
        height, width = frame.shape[:2]

        def mk(class_name: str, x: int, y: int, w: int, h: int, conf_base: float, jitter: float) -> ObjectDetection:
            # All motion is a pure function of the tick → reproducible output.
            wobble = 0.5 + 0.5 * math.sin(t * jitter + self._phase)
            center = max(0.0, min(1.0, conf_base + 0.08 * (wobble - 0.5)))
            box = Box(x, y, w, h).clamp(width, height)
            return ObjectDetection(class_name=class_name, confidence=round(center, 3), bounding_box=box, timestamp=ts)

        p_w = max(60, int(width * 0.09))
        p_h = max(220, int(height * 0.42))
        person_cx = int(width * (0.55 + 0.35 * math.sin(t / 8.0)))
        person_x = max(0, person_cx - p_w // 2)

        b_w = max(80, int(width * 0.11))
        b_h = max(70, int(height * 0.12))

        detections = [
            mk("person", person_x, int(height * 0.02), p_w, p_h, 0.78, 0.7),
            mk("experiment_box", int(width * 0.03), int(height * 0.45), b_w, b_h, 0.66, 0.3),
            mk("red_box", int(width * 0.16), int(height * 0.48), int(b_w * 0.8), int(b_h * 0.8), 0.84, 0.9),
            mk("yellow_box", int(width * 0.40), int(height * 0.50), int(b_w * 0.8), int(b_h * 0.8), 0.91, 0.5),
            mk("target_area", int(width * 0.62), int(height * 0.72), int(width * 0.28), int(height * 0.14), 0.55, 0.4),
        ]
        return detections
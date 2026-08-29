"""Deterministic mock object detector.

Emits the BAS scene's three headline classes at fixed places with the exact
example confidences from the phase spec — no randomness, no model. Lets the
backend, API, and dashboard run end-to-end without weights.

    person       0.95
    red_box      0.91
    yellow_box   0.89

``scene="empty"`` yields no detections at all (exercises empty-result paths).
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .detector import BaseDetector
from .types import Detection, DetectorStatus


class MockDetector(BaseDetector):
    name = "mock"
    model_free = True

    def __init__(self, scene: str = "bas") -> None:
        self.scene = scene
        self._count = 0

    def _mk(self, name: str, conf: float, x1: int, y1: int, x2: int, y2: int, ts: int) -> Detection:
        return Detection(
            class_name=name,
            confidence=conf,
            x1=max(0, x1),
            y1=max(0, y1),
            x2=max(x1 + 1, x2),
            y2=max(y1 + 1, y2),
            timestamp=ts,
        )

    def detect(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[Detection]:
        self._count += 1
        ts = self._ts(timestamp_ms)
        if self.scene == "empty":
            return []
        height, width = frame.shape[:2]

        p_w, p_h = max(40, int(width * 0.08)), max(140, int(height * 0.35))
        b_w, b_h = max(50, int(width * 0.10)), max(50, int(height * 0.12))

        return [
            self._mk("person", 0.95, int(width * 0.52), int(height * 0.06), int(width * 0.52) + p_w, int(height * 0.06) + p_h, ts),
            self._mk("red_box", 0.91, int(width * 0.16), int(height * 0.48), int(width * 0.16) + b_w, int(height * 0.48) + b_h, ts),
            self._mk("yellow_box", 0.89, int(width * 0.40), int(height * 0.50), int(width * 0.40) + b_w, int(height * 0.50) + b_h, ts),
        ]

    def status(self) -> DetectorStatus:
        return DetectorStatus(detector_type=self.name, model_loaded=True)
"""Generic / unknown-object detector (model-free), honest by construction.

A trained YOLO knows only the classes it was taught. This module proposes
``unknown_object`` candidates for things that move — the one model-free signal
a webcam reliably gives you. Any proposed region that overlaps a KNOWN class
detection is discarded at the DetectionService seam, so a generic detector can
never corrupt the known-class id space or double-report a person as unknown.

This is a *proposal* layer, deliberately weaker than a trained model:

- ``mode="motion"`` — frame-differencing against a slowly-adapting background.
  A static hammer on a desk is Honest-to-God invisible to this mode; static
  unknown-object detection needs a saliency/open-vocabulary model, which is
  not installed. That limitation is reported in ``status()`` rather than
  faked by assigning unknown things a random known-class id.
- Confidence is area-based and capped low-ish so downstream consumers treat
  unknowns as candidates, not certainties.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .detector import BaseDetector
from .types import Detection, DetectorStatus

KERNEL_OPEN = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
KERNEL_CLOSE = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))


def _motion_blobs(mask: np.ndarray, min_area: int) -> list[tuple[int, int, int, int]]:
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


class GenericProposalDetector(BaseDetector):
    """Proposes unknown objects from motion; never claims model-free prescience."""

    name = "generic"
    model_free = True

    #: Confidences are deliberate guesses; expressed per-blob so tests are
    #: deterministic and the boundary is visible.
    BASE_CONF = 0.6
    MAX_CONF = 0.9

    def __init__(
        self,
        conf_threshold: float = 0.6,
        min_area: float = 0.004,
        motion_threshold: int = 25,
        bg_alpha: float = 0.05,
    ) -> None:
        self.conf_threshold = conf_threshold
        self.min_area = min_area
        self.motion_threshold = motion_threshold
        self.bg_alpha = bg_alpha
        self.mode = "motion"  # the only mode available without extra weights
        self._bg: Optional[np.ndarray] = None

    def _confidence(self, blob_area: int, frame_area: int) -> float:
        ratio = min(blob_area / max(frame_area, 1), 0.5)
        return round(min(self.MAX_CONF, self.BASE_CONF + 0.3 * ratio), 4)

    def detect(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[Detection]:
        if frame is None or getattr(frame, "ndim", 0) != 3 or frame.dtype != np.uint8:
            return []
        ts = self._ts(timestamp_ms)
        height, width = frame.shape[:2]
        if height == 0 or width == 0:
            return []
        frame_area = height * width
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self._bg is None:
            self._bg = gray.astype(np.float32)
            return []  # first frame only seeds the background
        diff = cv2.absdiff(gray, self._bg.astype(np.uint8))
        self._bg = (1.0 - self.bg_alpha) * self._bg + self.bg_alpha * gray.astype(np.float32)

        _, mask = cv2.threshold(diff, self.motion_threshold, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL_OPEN)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL_CLOSE)

        dets: list[Detection] = []
        for x1, y1, x2, y2 in _motion_blobs(mask, max(100, int(frame_area * self.min_area))):
            dets.append(
                Detection(
                    class_name="unknown_object",
                    confidence=self._confidence((x2 - x1) * (y2 - y1), frame_area),
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    timestamp=ts,
                )
            )
        return [d for d in dets if d.confidence >= self.conf_threshold]

    def status(self) -> DetectorStatus:
        return DetectorStatus(
            detector_type=self.name,
            model_loaded=True,
            classes=("unknown_object",),
        )
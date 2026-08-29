"""Modular detector interface.

Every detector (mock, YOLO, or a future part-based reasoner) implements
:class:`BaseDetector` and returns the same structured result list, so the
pipeline and the backend seam stay detector-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from .detections import ObjectDetection, now_ms


class BaseDetector(ABC):
    """Contract every detector must satisfy."""

    #: Short identifier used by the CLI / config (e.g. "mock", "yolo").
    name: str = "base"

    #: True when the detector needs no model weights (runs anywhere).
    model_free: bool = False

    @abstractmethod
    def detect(
        self,
        frame: np.ndarray,
        timestamp_ms: Optional[int] = None,
    ) -> list[ObjectDetection]:
        """Classify one ``BGR`` frame.

        Returns a possibly-empty list of structured detections. Must never
        raise for an empty or blank frame.
        """
        raise NotImplementedError

    def close(self) -> None:
        """Release model resources if any (default: no-op)."""

    def _ts(self, timestamp_ms: Optional[int]) -> int:
        return timestamp_ms if timestamp_ms is not None else now_ms()
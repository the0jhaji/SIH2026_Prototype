"""Generic detector interface plus a small factory.

The backend and dashboard depend on :class:`BaseDetector`, never on YOLO or
the mock directly — swap implementations behind the same ``detect`` contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from .types import DetectorStatus, Detection, now_ms


class BaseDetector(ABC):
    """Contract every detector implementation must satisfy."""

    #: Short identifier used by config and status (e.g. "mock", "yolo").
    name: str = "base"

    #: True when the detector needs no model weights.
    model_free: bool = False

    @abstractmethod
    def detect(
        self,
        frame: np.ndarray,
        timestamp_ms: Optional[int] = None,
    ) -> list[Detection]:
        """Classify one ``BGR`` frame.

        Returns a possibly-empty list of structured detections. Must not
        raise for blank or empty frames.
        """
        raise NotImplementedError

    def load(self) -> None:
        """Load model weights if there are any (mock: no-op). Raises a clear
        error when weights are missing or unreadable."""

    def status(self) -> DetectorStatus:
        """Health of this detector (model loaded, path, class list)."""
        return DetectorStatus(detector_type=self.name, model_loaded=self.model_free)

    def close(self) -> None:
        """Release model resources if any (default: no-op)."""

    def _ts(self, timestamp_ms: Optional[int]) -> int:
        return timestamp_ms if timestamp_ms is not None else now_ms()


def create_detector(
    kind: str,
    model_path: str | None = None,
    classes: Optional[list[str]] = None,
    conf_threshold: float = 0.5,
    use_cuda: bool = False,
) -> BaseDetector:
    """Build a detector instance by short name.

    - ``mock`` — deterministic synthetic detections, no weights.
    - ``yolo`` — YOLOv8 ONNX via OpenCV DNN (weights in ``models/detection/``).
    - ``heuristic`` — real, model-free HSV color + motion detection.
    """
    from .heuristic_detector import ColorMotionDetector
    from .mock_detector import MockDetector
    from .yolo_detector import YoloDetector

    if kind == "mock":
        return MockDetector()
    if kind == "yolo":
        return YoloDetector(
            model_path=model_path,
            classes=classes,
            conf_threshold=conf_threshold,
            use_cuda=use_cuda,
        )
    if kind == "heuristic":
        return ColorMotionDetector(conf_threshold=conf_threshold)
    raise ValueError(f"Unknown detector kind: {kind!r} (expected 'mock', 'yolo' or 'heuristic')")
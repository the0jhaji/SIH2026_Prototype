"""Structured detection types for the local object-detection layer.

Independent of the (older) ``ai.pipeline`` JSON contract on purpose: the
backend and dashboard consume this shape, so the camera→detector seam stays
stable no matter which detector is plugged in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Detection:
    """One structured detection in pixel space.

    Coordinates are ``(x1, y1)`` top-left and ``(x2, y2)`` bottom-right,
    exclusive — the same convention OpenCV rectangles use.

    ``instance_id`` is only set for generic/unknown-object detections (a stable
    per-track label like ``unknown-3``); known-class detections leave it None so
    the plain 7-field payload shape is unchanged.
    """

    class_name: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    timestamp: int  # epoch milliseconds
    instance_id: Optional[str] = None

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def to_dict(self) -> dict:
        """Plain JSON-ready structure with the exact fields of this phase."""
        payload = {
            "class_name": self.class_name,
            "confidence": round(float(self.confidence), 4),
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "timestamp": self.timestamp,
        }
        if self.instance_id is not None:
            payload["instance_id"] = self.instance_id
        return payload


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class DetectorStatus:
    """Reported by every detector about its own health.

    The extra fields are the runtime model identity that the startup banner and
    ``/api/detection/status`` print, so "which model is actually loaded, with
    how many classes, at what size and threshold" is answerable from the API
    rather than guessed from config.
    """

    detector_type: str = ""
    model_loaded: bool = False
    model_path: str | None = None
    classes: tuple[str, ...] = field(default_factory=tuple)
    input_size: int | None = None
    conf_threshold: float | None = None
    iou_threshold: float | None = None
    model_size_mb: float | None = None
    #: False for a narrow (specialised) vocabulary that cannot detect people etc.
    general_purpose: bool | None = None
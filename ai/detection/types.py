"""Structured detection types for the local object-detection layer.

Independent of the (older) ``ai.pipeline`` JSON contract on purpose: the
backend and dashboard consume this shape, so the camera→detector seam stays
stable no matter which detector is plugged in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Detection:
    """One structured detection in pixel space.

    Coordinates are ``(x1, y1)`` top-left and ``(x2, y2)`` bottom-right,
    exclusive — the same convention OpenCV rectangles use.
    """

    class_name: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    timestamp: int  # epoch milliseconds

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def to_dict(self) -> dict:
        """Plain JSON-ready structure with the exact fields of this phase."""
        return {
            "class_name": self.class_name,
            "confidence": round(float(self.confidence), 4),
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "timestamp": self.timestamp,
        }


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class DetectorStatus:
    """Reported by every detector about its own health."""

    detector_type: str = ""
    model_loaded: bool = False
    model_path: str | None = None
    classes: tuple[str, ...] = field(default_factory=tuple)
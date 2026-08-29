"""Structured detections shared by every detector implementation."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    """Pixel-space bounding box (top-left origin, as used by OpenCV)."""

    x: int
    y: int
    width: int
    height: int

    @property
    def cx(self) -> float:
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2

    def clamp(self, frame_width: int, frame_height: int) -> "Box":
        """Clip the box so it stays inside a frame of the given size."""
        x2 = min(max(self.x + self.width, 0), frame_width)
        y2 = min(max(self.y + self.height, 0), frame_height)
        return Box(
            x=min(max(self.x, 0), frame_width),
            y=min(max(self.y, 0), frame_height),
            width=max(0, x2 - min(max(self.x, 0), frame_width)),
            height=max(0, y2 - min(max(self.y, 0), frame_height)),
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class ObjectDetection:
    """One structured detection returned by a detector for a single frame.

    Fields mirror the JSON contract (``class_name``, ``confidence``,
    ``bounding_box``, ``timestamp``) so downstream consumers never depend on
    which detector produced it.
    """

    class_name: str
    confidence: float
    bounding_box: Box
    timestamp: int  # epoch milliseconds

    def to_dict(self) -> dict:
        """Plain JSON-ready structure, e.g.::

            {"class_name": "red_box", "confidence": 0.93,
             "bounding_box": [412, 188, 96, 74], "timestamp": 1725000000000}
        """
        return {
            "class_name": self.class_name,
            "confidence": round(float(self.confidence), 4),
            "bounding_box": list(self.bounding_box.as_tuple()),
            "timestamp": self.timestamp,
        }


def now_ms() -> int:
    return int(time.time() * 1000)
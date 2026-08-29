"""Bounding-box rendering on a copy of the frame."""

from __future__ import annotations

from typing import Mapping

import cv2
import numpy as np

from .detections import ObjectDetection

#: BGR colours per class; any unknown class falls back to a cycling palette.
CLASS_COLORS: Mapping[str, tuple[int, int, int]] = {
    "person": (255, 160, 0),
    "experiment_box": (200, 200, 200),
    "red_box": (0, 0, 255),
    "yellow_box": (0, 215, 255),
    "target_area": (0, 235, 160),
}

_PALETTE: list[tuple[int, int, int]] = [
    (232, 176, 16),
    (64, 224, 208),
    (255, 165, 20),
    (0, 128, 255),
    (32, 178, 170),
    (238, 130, 238),
]


def _color_for(class_name: str, index: int) -> tuple[int, int, int]:
    if class_name in CLASS_COLORS:
        return CLASS_COLORS[class_name]
    return _PALETTE[index % len(_PALETTE)]


def draw_detections(
    frame: np.ndarray,
    detections: list[ObjectDetection],
    font_scale: float = 0.6,
    line_thickness: int = 2,
) -> np.ndarray:
    """Draw boxes + ``class_name confidence`` labels on a copy of ``frame``.

    Always returns a new BGR image (never mutates the input), so the raw
    frame can still be forwarded to the perception backend.
    """
    out = frame.copy()
    for i, det in enumerate(detections):
        color = _color_for(det.class_name, i)
        x, y, w, h = det.bounding_box.as_tuple()
        x2, y2 = x + w, y + h
        cv2.rectangle(out, (x, y), (x2, y2), color, line_thickness)
        label = f"{det.class_name} {det.confidence:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        label_y = y - 6 if y - th - 6 >= 0 else y + h + th + 4
        cv2.rectangle(out, (x, label_y - th - 4), (x + tw + 4, label_y + 4), color, -1)
        cv2.putText(
            out,
            label,
            (x + 2, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    return out
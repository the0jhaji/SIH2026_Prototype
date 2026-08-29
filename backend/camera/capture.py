"""Camera capture layer: frame readers for a real webcam (OpenCV) and a
synthetic mock camera, plus the configurable settings shared with the manager.

Everything here stays local — no network, no cloud services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


class CameraError(Exception):
    """Raised when a camera device cannot be opened or misbehaves."""


@dataclass(frozen=True)
class CameraSettings:
    camera_index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    mock: bool = False
    jpeg_quality: int = 70


class FrameReader(ABC):
    """Contract every camera source satisfies (real or mock)."""

    @abstractmethod
    def open(self) -> bool:
        """Acquire the device. Returns False when unavailable."""

    @abstractmethod
    def read(self) -> Optional[np.ndarray]:
        """Block until the next frame. Returns None when the feed fails."""

    @abstractmethod
    def release(self) -> None:
        """Free the device. Idempotent."""


class OpenCVCamera(FrameReader):
    """Live webcam capture via ``cv2.VideoCapture``."""

    name = "webcam"

    def __init__(self, settings: CameraSettings) -> None:
        self.settings = settings
        self._capture: Optional[cv2.VideoCapture] = None

    def open(self) -> bool:
        capture = cv2.VideoCapture(self.settings.camera_index)
        if not capture.isOpened():
            capture.release()
            return False
        setting = self.settings
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, setting.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, setting.height)
        if setting.fps > 0:
            capture.set(cv2.CAP_PROP_FPS, setting.fps)
        self._capture = capture
        return True

    def read(self) -> Optional[np.ndarray]:
        if self._capture is None:
            return None
        ok, frame = self._capture.read()
        return frame if ok else None

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class MockCamera(FrameReader):
    """Synthetic frames so development and tests never need a webcam.

    Renders a moving target box plus a running frame counter — visually
    distinct from a live feed. ``open_ok=False`` simulates a camera that
    cannot be opened (the manager reports CAMERA ERROR).
    """

    name = "mock"

    def __init__(self, settings: CameraSettings, open_ok: bool = True, fail_after: Optional[int] = None) -> None:
        self.settings = settings
        self._open_ok = open_ok
        self._fail_after = fail_after
        self._count = 0

    def open(self) -> bool:
        if not self._open_ok:
            return False
        self._count = 0
        return True

    def read(self) -> Optional[np.ndarray]:
        if self._fail_after is not None and self._count >= self._fail_after:
            return None
        self._count += 1
        w, h = self.settings.width, self.settings.height
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (18, 24, 34)  # slate background
        step = self._count
        cx = (step * 6) % max(w - 160, 1)
        cy = h // 2 + int(np.sin(step / 6.0) * h * 0.25)
        cv2.rectangle(frame, (cx, cy), (cx + 120, cy + 80), (68, 90, 220), -1)
        cv2.rectangle(frame, (cx + 24, cy + 16), (cx + 96, cy + 64), (30, 60, 200), -1)
        label = f"MOCK CAMERA {step:04d}"
        cv2.putText(frame, label, (w // 2 - 140, h // 2 - 120), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (210, 210, 215), 2)
        cv2.putText(frame, f"{w}x{h}", (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 160, 180), 1)
        return frame

    def release(self) -> None:
        pass
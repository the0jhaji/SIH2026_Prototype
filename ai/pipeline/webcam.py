"""Webcam capture and frame sources.

``WebcamSource`` wraps ``cv2.VideoCapture``; ``NullSource`` yields synthetic
black frames so the pipeline demos without any camera. Both implement the
same :class:`FrameSource` interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import cv2
import numpy as np


class FrameSource(ABC):
    """Frame producer abstraction (camera, file, synthetic)."""

    @abstractmethod
    def open(self) -> bool:
        """Acquire the source. Returns False if unavailable."""

    @abstractmethod
    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        """Return ``(ok, frame)``; ``frame`` is None when the stream ends."""

    @abstractmethod
    def release(self) -> None:
        """Free the source. Idempotent."""

    @property
    @abstractmethod
    def width(self) -> int: ...

    @property
    @abstractmethod
    def height(self) -> int: ...

    def __enter__(self) -> "FrameSource":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class WebcamSource(FrameSource):
    """Live webcam capture via OpenCV."""

    def __init__(self, index: int = 0, width: Optional[int] = None, height: Optional[int] = None) -> None:
        self.index = index
        self._requested = (width, height)
        self._capture: Optional[cv2.VideoCapture] = None

    @property
    def width(self) -> int:
        if self._capture is None:
            return self._requested[0] or 640
        return int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))

    @property
    def height(self) -> int:
        if self._capture is None:
            return self._requested[1] or 480
        return int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def open(self) -> bool:
        capture = cv2.VideoCapture(self.index)
        width, height = self._requested
        if width:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not capture.isOpened():
            capture.release()
            return False
        self._capture = capture
        return True

    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        if self._capture is None:
            return False, None
        ok, frame = self._capture.read()
        return (ok, frame if ok else None)

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class NullSource(FrameSource):
    """Synthetic black frames at a fixed resolution — no hardware needed."""

    def __init__(self, width: int = 1280, height: int = 720, max_frames: Optional[int] = None) -> None:
        self._width = width
        self._height = height
        self._max_frames = max_frames
        self._count = 0

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def open(self) -> bool:
        self._count = 0
        return True

    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        if self._max_frames is not None and self._count >= self._max_frames:
            return False, None
        self._count += 1
        return True, np.zeros((self._height, self._width, 3), dtype=np.uint8)

    def release(self) -> None:
        pass
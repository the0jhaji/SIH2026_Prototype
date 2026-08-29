"""Local webcam capture + MJPEG streaming (Phase 2).

Exports the configurable settings, the two frame readers (real OpenCV camera
and a mock camera for camera-free development), and the thread-backed
manager that owns capture life-cycle.

    WEBCAM → OpenCV → CameraManager → MJPEG stream → React GUI
"""

from .capture import CameraError, CameraSettings, FrameReader, MockCamera, OpenCVCamera
from .manager import CameraManager, CameraStatus

__all__ = [
    "CameraError",
    "CameraManager",
    "CameraSettings",
    "CameraStatus",
    "FrameReader",
    "MockCamera",
    "OpenCVCamera",
]
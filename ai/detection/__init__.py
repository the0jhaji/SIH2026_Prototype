"""ai.detection — local object detection layer (mock + YOLO ONNX).

Consumed by the backend's ``DetectionService`` via this package's
:class:`BaseDetector` interface; never depends on FastAPI.
"""

from .detector import BaseDetector, create_detector
from .types import Detection, DetectorStatus

__all__ = ["BaseDetector", "create_detector", "Detection", "DetectorStatus"]
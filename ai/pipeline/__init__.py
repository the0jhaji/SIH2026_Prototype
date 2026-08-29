"""Local computer-vision perception pipeline.

Independent of FastAPI by design — the detector interface consumes raw
``BGR`` frames and returns structured :class:`ObjectDetection` lists. The
backend seam (converting these into :class:`Detection` activity events) is a
separate module added in a later phase.
"""

from .base import BaseDetector
from .detections import Box, ObjectDetection
from .hand import BaseHandTracker, HandLandmark, HandLandmarkSet, MockHandTracker
from .interaction import InteractionConfig, InteractionEvent, InteractionTracker
from .mock import MockDetector
from .pipeline import CameraPipeline, DetectionFrame
from .webcam import FrameSource, NullSource, WebcamSource
from .yolo import YoloDetector

__all__ = [
    "BaseDetector",
    "Box",
    "ObjectDetection",
    "BaseHandTracker",
    "HandLandmark",
    "HandLandmarkSet",
    "MockHandTracker",
    "InteractionConfig",
    "InteractionEvent",
    "InteractionTracker",
    "MockDetector",
    "CameraPipeline",
    "DetectionFrame",
    "FrameSource",
    "NullSource",
    "WebcamSource",
    "YoloDetector",
]
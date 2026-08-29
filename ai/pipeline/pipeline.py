"""Frame-loop orchestrator: source → detector → annotation.

Emits :class:`DetectionFrame` results through a callback. Deliberately has no
knowledge of FastAPI, the state machine, or the backend — a later phase wires
these detections into ``Detection(activity, confidence, ts)`` events.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .annotate import draw_detections
from .base import BaseDetector
from .detections import ObjectDetection
from .webcam import FrameSource


@dataclass
class DetectionFrame:
    frame: Optional[np.ndarray]  # raw BGR frame (None if stream ended)
    annotated: Optional[np.ndarray]  # frame + boxes, or None if annotation off
    detections: list[ObjectDetection] = field(default_factory=list)
    timestamp: int = 0  # epoch ms
    frame_index: int = 0


class CameraPipeline:
    def __init__(self, source: FrameSource, detector: BaseDetector, annotate: bool = True) -> None:
        self.source = source
        self.detector = detector
        self.annotate = annotate

    def run(
        self,
        on_frame: Callable[[DetectionFrame], None],
        stop_event: Optional[threading.Event] = None,
        max_frames: Optional[int] = None,
    ) -> None:
        """Consume frames, classify, annotate, and hand each result to
        ``on_frame``. Runs on the calling thread. The source is released
        before returning (idempotent for NullSource, required for cameras).
        """
        try:
            if not self.source.open():
                raise RuntimeError(
                    f"Frame source unavailable (detector={self.detector.name}). "
                    f"Try --source null for a headless demo, or a different --camera index."
                )
            count = 0
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                ok, frame = self.source.read()
                if not ok or frame is None:
                    break
                ts = int(time.time() * 1000)
                detections = self.detector.detect(frame, timestamp_ms=ts)
                annotated = draw_detections(frame, detections) if self.annotate else None
                on_frame(
                    DetectionFrame(
                        frame=frame,
                        annotated=annotated,
                        detections=detections,
                        timestamp=ts,
                        frame_index=count,
                    )
                )
                count += 1
                if max_frames is not None and count >= max_frames:
                    break
        finally:
            self.source.release()
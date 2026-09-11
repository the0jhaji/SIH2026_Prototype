"""YOLO object detector via OpenCV DNN (ONNX export), CPU-first.

Model path is fully configurable; nothing is ever downloaded at runtime — a
missing file raises a clear ``FileNotFoundError`` instead of crashing the app,
and the backend records it as an ERROR status. Weight loading (``load()``) is
separate from inference (``detect()``) so a custom-trained model can be
swapped in without touching the caller.

Class names: by default the Astra AI scene classes. If a ``.names`` file sits
next to the ONNX model (one class name per line, index-aligned), it overrides
the list — that is how a future custom-trained model carries its own labels.

A generic pretrained YOLO model does NOT reliably recognize
``experiment_box`` / ``red_box`` / ``yellow_box`` / ``target_area`` — those
classes only exist after training (see ``models/detection/README.md``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import cv2
import numpy as np

from .detector import BaseDetector
from .types import Detection, DetectorStatus

from ai.pipeline.yolo import DEFAULT_CLASSES, letterbox, postprocess_yolov8, resolve_weights_path

DEFAULT_MODEL = "detection/yolov8n.onnx"


def _read_names_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    names = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return names


class YoloDetector(BaseDetector):
    name = "yolo"
    model_free = False

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        classes: Optional[Sequence[str]] = None,
        input_size: int = 640,
        conf_threshold: float = 0.5,
        iou_threshold: float = 0.45,
        use_cuda: bool = False,
        names_path: Optional[str] = None,
        cv_threads: Optional[int] = None,
    ) -> None:
        self.model_path = model_path
        self.classes = list(classes) if classes else list(DEFAULT_CLASSES)
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.use_cuda = use_cuda
        self.names_path = names_path
        self.cv_threads = cv_threads
        self._net: Optional[cv2.dnn.Net] = None
        self._weights: Path | None = None
        self._error: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self._net is not None

    def load(self) -> None:
        """Load the ONNX weights if not already loaded. Raises a clear error
        when the file is missing or unreadable (the app stays alive — the
        backend simply reports an ERROR status)."""
        if self.is_loaded:
            return
        resolved = resolve_weights_path(self.model_path)
        if not resolved.exists():
            raise FileNotFoundError(
                f"YOLO model weights not found: {resolved}. Export a trained model "
                f"to ONNX and place it in models/detection/ (see models/detection/README.md), "
                f"or point BAS_MODELS_DIR at the directory containing it."
            )
        names_path = resolve_weights_path(self.names_path) if self.names_path else resolved.with_suffix(".names")
        names = _read_names_file(names_path)
        if names:
            self.classes = names
        net = cv2.dnn.readNetFromONNX(str(resolved))
        if self.cv_threads and self.cv_threads > 0:
            # OpenCV caps the parallel worker pool process-wide (no per-Net API).
            cv2.setNumThreads(self.cv_threads)
        if self.use_cuda:
            try:
                net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
            except cv2.error:
                pass  # non-CUDA OpenCV build → keep CPU (default path)
        self._net = net
        self._weights = resolved
        self._error = None

    def detect(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[Detection]:
        if self._net is None:
            self.load()
        assert self._net is not None
        h, w = frame.shape[:2]
        canvas, scale, dx, dy = letterbox(frame, self.input_size)
        blob = cv2.dnn.blobFromImage(
            canvas, 1.0 / 255.0, (self.input_size, self.input_size), swapRB=True
        )
        self._net.setInput(blob)
        outputs = self._net.forward()
        ts = self._ts(timestamp_ms)
        decoded = postprocess_yolov8(
            outputs,
            input_size=self.input_size,
            scale=scale,
            dx=dx,
            dy=dy,
            frame_width=w,
            frame_height=h,
            classes=self.classes,
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
        )
        return [
            Detection(
                class_name=d.class_name,
                confidence=d.confidence,
                x1=d.bounding_box.x,
                y1=d.bounding_box.y,
                x2=d.bounding_box.x + d.bounding_box.width,
                y2=d.bounding_box.y + d.bounding_box.height,
                timestamp=ts,
            )
            for d in decoded
        ]

    def status(self) -> DetectorStatus:
        path = str(self._weights) if self._weights else str(resolve_weights_path(self.model_path))
        return DetectorStatus(
            detector_type=self.name,
            model_loaded=self.is_loaded,
            model_path=path,
            classes=tuple(self.classes),
        )

    def close(self) -> None:
        self._net = None
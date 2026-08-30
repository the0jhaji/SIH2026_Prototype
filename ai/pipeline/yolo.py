"""YOLO detector via OpenCV DNN (ONNX export).

Reads a local ``.onnx`` model — never downloads anything. Export a trained
model with e.g. ``yolo export model=yolov8n.pt format=onnx`` and drop the
file into ``models/yolo/`` (see ``models/README.md``). The default class list
matches the Astra AI scene; supply a different list if your model uses other
indices.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Sequence

import cv2
import numpy as np

from .base import BaseDetector
from .detections import Box, ObjectDetection

#: Astra AI scene classes, index-aligned with a 5-class YOLO model.
DEFAULT_CLASSES = ["person", "experiment_box", "red_box", "yellow_box", "target_area"]

DEFAULT_MODEL = "yolov8n.onnx"


def resolve_weights_path(path: str | Path) -> Path:
    """Resolve a model path: absolute first, then ``BAS_MODELS_DIR``, then
    the repo's ``models/`` directory."""
    p = Path(path)
    if p.is_absolute():
        return p
    env_dir = os.environ.get("BAS_MODELS_DIR")
    if env_dir:
        cand = Path(env_dir) / p
        if cand.exists():
            return cand
    root = Path(__file__).resolve().parent.parent.parent  # repo root
    return root / "models" / p


def letterbox(
    image: np.ndarray,
    size: int,
    fill: int = 114,
) -> tuple[np.ndarray, float, float, float]:
    """Resize keeping aspect ratio and letterbox-pad to a ``size`` square.

    Returns ``(canvas, scale, dx, dy)`` where ``scale`` converts original
    pixels to canvas pixels and ``(dx, dy)`` is the top-left padding offset
    in canvas pixels. Inverse: ``orig = (canvas - offset) / scale``.
    """
    h, w = image.shape[:2]
    scale = min(size / w, size / h)
    nw = round(w * scale)
    nh = round(h * scale)
    if nw != w or nh != h:
        resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)
    else:
        resized = image
    canvas = np.full((size, size, 3), fill, dtype=np.uint8)
    dx = (size - nw) / 2.0
    dy = (size - nh) / 2.0
    x0, y0 = int(dx), int(dy)
    canvas[y0 : y0 + nh, x0 : x0 + nw] = resized
    return canvas, scale, dx, dy


def postprocess_yolov8(
    outputs: np.ndarray,
    input_size: int,
    scale: float,
    dx: float,
    dy: float,
    frame_width: int,
    frame_height: int,
    classes: Sequence[str],
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> list[ObjectDetection]:
    """Decode a YOLOv8 ONNX output tensor (``(1, 4 + C, N)`` or transposed)
    back into original-frame pixel space. Coordinates from the network are
    normalized to ``[0, 1]`` relative to the letterboxed ``input_size``."""
    arr = np.asarray(outputs, dtype=np.float32)
    num_classes = len(classes)
    if arr.ndim == 3:
        arr = arr[0]
    # Orient rows = detections, columns = features (4 + C). YOLOv8 exports
    # may be (4 + C, N) or (N, 4 + C); models trained with more classes than
    # the configured list widen the feature axis, so detect that case too.
    if arr.shape[1] != 4 + num_classes and (
        arr.shape[0] == 4 + num_classes or arr.shape[1] < arr.shape[0]
    ):
        arr = arr.T
    assert arr.shape[1] >= 4 + num_classes, (
        f"model output width {arr.shape[1]} < 4 + {num_classes} classes"
    )

    class_scores = arr[:, 4:]
    scores = class_scores.max(axis=1)
    class_ids = class_scores.argmax(axis=1)
    keep = scores >= conf_threshold
    # Drop entries whose top class is outside the configured class list.
    keep &= class_ids < num_classes
    if not keep.any():
        return []

    rows = arr[keep]
    scores = scores[keep]
    class_ids = class_ids[keep]

    candidates: list[tuple[Box, float, str]] = []
    for row, score, cid in zip(rows, scores, class_ids):
        cx, cy, bw, bh = row[0], row[1], row[2], row[3]
        # canvas (letterbox) pixel space: normalized 0..1 × input_size
        x1 = (cx * input_size - bw * input_size / 2 - dx) / scale
        y1 = (cy * input_size - bh * input_size / 2 - dy) / scale
        x2 = (cx * input_size + bw * input_size / 2 - dx) / scale
        y2 = (cy * input_size + bh * input_size / 2 - dy) / scale
        box = Box(
            x=round(x1),
            y=round(y1),
            width=round(x2 - x1),
            height=round(y2 - y1),
        ).clamp(frame_width, frame_height)
        if box.width <= 0 or box.height <= 0:
            continue
        candidates.append((box, float(score), classes[int(cid)]))

    if not candidates:
        return []

    # Class-aware NMS: suppress duplicates within each class, never across.
    selected: list[tuple[Box, float, str]] = []
    by_label: dict[str, list[tuple[Box, float]]] = {}
    for box, score, label in candidates:
        by_label.setdefault(label, []).append((box, score))
    for label, items in by_label.items():
        boxes = [box.as_tuple() for box, _ in items]
        indices = cv2.dnn.NMSBoxes(
            boxes, [score for _, score in items], conf_threshold, iou_threshold
        )
        if indices is None or len(indices) == 0:
            continue
        for i in np.atleast_1d(indices):
            selected.append((items[int(i)][0], items[int(i)][1], label))

    selected.sort(key=lambda item: item[1], reverse=True)
    return [
        ObjectDetection(class_name=label, confidence=conf, bounding_box=box, timestamp=0)
        for box, conf, label in selected
    ]


class YoloDetector(BaseDetector):
    name = "yolo"
    model_free = False

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        classes: Optional[Sequence[str]] = None,
        input_size: int = 640,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        use_cuda: bool = False,
    ) -> None:
        self.model_path = model_path
        self.classes = list(classes) if classes else list(DEFAULT_CLASSES)
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.use_cuda = use_cuda
        self._net: Optional[cv2.dnn.Net] = None

    def load(self) -> None:
        path = resolve_weights_path(self.model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"YOLO model weights not found: {path}. Export a trained model "
                f"to ONNX and place it in models/yolo/ (see models/README.md), "
                f"or point BAS_MODELS_DIR at the directory containing it."
            )
        net = cv2.dnn.readNetFromONNX(str(path))
        if self.use_cuda:
            try:
                net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
            except cv2.error:
                pass  # CUDA build absent → CPU fallback
        self._net = net

    def detect(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[ObjectDetection]:
        if self._net is None:
            self.load()
        h, w = frame.shape[:2]
        canvas, scale, dx, dy = letterbox(frame, self.input_size)
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 255.0, (self.input_size, self.input_size), swapRB=True)
        assert self._net is not None
        self._net.setInput(blob)
        outputs = self._net.forward()
        detections = postprocess_yolov8(
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
        ts = self._ts(timestamp_ms)
        return [
            ObjectDetection(class_name=d.class_name, confidence=d.confidence, bounding_box=d.bounding_box, timestamp=ts)
            for d in detections
        ]

    def close(self) -> None:
        self._net = None
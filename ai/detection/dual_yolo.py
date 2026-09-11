"""Dual YOLO detector: runs a general COCO model + a custom experiment model
on the same frame and merges results with cross-model NMS.

Runs models sequentially — parallel ONNX inference on CPU causes thread
contention and is measurably slower. Other optimizations: cv_threads=1
per model (prevents OpenCV over-threading), vectorized postprocessing,
no poll delay in detection loop.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .detector import BaseDetector
from .types import Detection, DetectorStatus
from .yolo_detector import YoloDetector

logger = logging.getLogger("astraai.detection")


def _iou(a: Detection, b: Detection) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    if inter <= 0.0:
        return 0.0
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union > 0.0 else 0.0


class DualYoloDetector(BaseDetector):
    """Runs general + custom YOLO models sequentially, merges with cross-model NMS."""

    name = "yolo"
    model_free = False

    def __init__(
        self,
        general_path: str = "detection/yolov8n.onnx",
        custom_path: str = "detection/experiment_custom.onnx",
        conf_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        cross_model_iou: float = 0.3,
        use_cuda: bool = False,
        cv_threads: Optional[int] = None,
    ) -> None:
        self._general = YoloDetector(
            model_path=general_path,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            use_cuda=use_cuda,
            cv_threads=cv_threads,
        )
        self._custom = YoloDetector(
            model_path=custom_path,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            use_cuda=use_cuda,
            cv_threads=cv_threads,
        )
        self._cross_model_iou = cross_model_iou
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._general.load()
        self._custom.load()
        self._loaded = True

    def detect(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[Detection]:
        if not self._loaded:
            self.load()
        ts = self._ts(timestamp_ms)
        try:
            general_dets = self._general.detect(frame, ts)
        except Exception as exc:
            logger.warning("General model error: %s", exc)
            general_dets = []
        try:
            custom_dets = self._custom.detect(frame, ts)
        except Exception as exc:
            logger.warning("Custom model error: %s", exc)
            custom_dets = []
        merged = general_dets + custom_dets
        return self._nms(merged)

    def _nms(self, detections: list[Detection]) -> list[Detection]:
        """Suppress overlapping boxes across both models."""
        if not detections:
            return []
        detections.sort(key=lambda d: d.confidence, reverse=True)
        keep: list[Detection] = []
        suppressed = set()
        for i, a in enumerate(detections):
            if i in suppressed:
                continue
            keep.append(a)
            for j in range(i + 1, len(detections)):
                if j in suppressed:
                    continue
                if _iou(a, detections[j]) >= self._cross_model_iou:
                    suppressed.add(j)
        return keep

    def status(self) -> DetectorStatus:
        general_status = self._general.status()
        custom_status = self._custom.status()
        all_classes = list(general_status.classes) + list(custom_status.classes)
        return DetectorStatus(
            detector_type="yolo",
            model_loaded=self._loaded,
            model_path=f"general={general_status.model_path} | custom={custom_status.model_path}",
            classes=tuple(all_classes),
        )

    def close(self) -> None:
        self._general.close()
        self._custom.close()
        self._loaded = False

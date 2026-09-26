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

import logging
from pathlib import Path
from typing import Optional, Sequence

import cv2
import numpy as np

from . import detect_log
from .detector import BaseDetector
from .types import Detection, DetectorStatus

from ai.pipeline.yolo import DEFAULT_CLASSES, letterbox, postprocess_yolov8, resolve_weights_path

logger = logging.getLogger("astraai.detection")

DEFAULT_MODEL = "detection/yolov8n.onnx"

#: A model with fewer classes than this cannot be a general-purpose detector.
#: ``experiment_custom.onnx`` (red_box/yellow_box) sits far below it.
_GENERAL_DETECTOR_MIN_CLASSES = 10


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
        self._blob: np.ndarray | None = None
        self._channels_checked = False

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
        detect_log.ensure_setup()
        if not resolved.exists():
            detect_log.dbg_error(
                "MODEL",
                f"weights_missing path={resolved} exists=false cannot_load=FileNotFoundError",
            )
            raise FileNotFoundError(
                f"YOLO model weights not found: {resolved}. Export a trained model "
                f"to ONNX and place it in models/detection/ (see models/detection/README.md), "
                f"or point BAS_MODELS_DIR at the directory containing it."
            )
        names_path = resolve_weights_path(self.names_path) if self.names_path else resolved.with_suffix(".names")
        names = _read_names_file(names_path)
        if names:
            self.classes = names
        try:
            net = cv2.dnn.readNetFromONNX(str(resolved))
        except cv2.error as exc:
            detect_log.dbg_error("MODEL", f"readNetFromONNX_failed path={resolved} err={exc}")
            raise
        if self.cv_threads and self.cv_threads > 0:
            cv2.setNumThreads(self.cv_threads)
        # else: leave OpenCV's auto thread selection alone. The previous code
        # called setNumThreads(1) here, which contradicted config.py's own
        # "0 leaves auto-detect untouched" comment and pinned inference to a
        # single core (measured 666ms vs 293ms at 8 threads on a 16-CPU host).
        if self.use_cuda:
            try:
                net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
            except cv2.error:
                pass
        self._net = net
        self._weights = resolved
        self._error = None
        self._warn_if_narrow()
        detect_log.dbg_info(
            "MODEL",
            f"loaded path={resolved} exists=true size_mb={resolved.stat().st_size / 1e6:.1f} "
            f"classes={len(self.classes)} input_size={self.input_size} device=cpu "
            f"conf={self.conf_threshold} iou={self.iou_threshold}",
        )

    def _warn_if_narrow(self) -> None:
        """A 2-class model is a *specialised* detector, never a general one.

        ``experiment_custom.onnx`` only knows red_box/yellow_box, so loading it
        as the sole detector makes every person, bottle, cup or laptop
        undetectable. That is a configuration mistake worth shouting about
        rather than silently serving an almost-empty frame.
        """
        if len(self.classes) >= _GENERAL_DETECTOR_MIN_CLASSES:
            return
        logger.warning(
            "Narrow vocabulary model loaded: %s has only %d classes (%s). "
            "It CANNOT be used as the general detector — person/bottle/cup/laptop "
            "etc. will never be reported. Use a general model (e.g. yolov8n.onnx, "
            "80 COCO classes) as the primary detector and keep this one for its "
            "own classes only (DETECTION_BACKEND=dual).",
            self.model_path, len(self.classes), ", ".join(self.classes),
        )

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
        self._check_channel_match(outputs)
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

    def _check_channel_match(self, outputs: np.ndarray) -> None:
        """Fail loudly when the label list and the network's channels disagree.

        A YOLOv8 head emits ``4 + num_classes`` channels. If the ``.names`` file
        is missing or wrong, the decoder would silently drop every class_id
        beyond the short list (``keep &= class_ids < num_classes``) and the app
        would appear to "only see person" with no error anywhere. That is the
        exact failure this check exists to make visible.
        """
        if self._channels_checked:
            return
        arr = np.asarray(outputs)
        if arr.ndim != 3:
            return
        channels = arr.shape[1]
        model_classes = channels - 4
        if model_classes != len(self.classes):
            raise ValueError(
                f"Class vocabulary mismatch for {self.model_path}: the network emits "
                f"{channels} channels ({model_classes} classes) but "
                f"{len(self.classes)} class names are configured "
                f"({', '.join(self.classes[:10])}). Fix the `.names` file next to the "
                f"ONNX (one index-aligned class per line) or pass an explicit "
                f"`classes` list — otherwise every class_id >= {len(self.classes)} is "
                f"silently discarded."
            )
        self._channels_checked = True

    def status(self) -> DetectorStatus:
        path = str(self._weights) if self._weights else str(resolve_weights_path(self.model_path))
        return DetectorStatus(
            detector_type=self.name,
            model_loaded=self.is_loaded,
            model_path=path,
            classes=tuple(self.classes),
            input_size=self.input_size,
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
            model_size_mb=(self._weights.stat().st_size / 1e6) if self._weights else None,
            general_purpose=len(self.classes) >= _GENERAL_DETECTOR_MIN_CLASSES,
        )

    def close(self) -> None:
        self._net = None
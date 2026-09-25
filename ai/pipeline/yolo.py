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
try:
    from ..detection import detect_log
except ImportError:  # ai venv imports `pipeline` as a top-level package
    from detection import detect_log

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
    """Decode a YOLOv8 ONNX output tensor back into original-frame pixel space."""
    arr = np.asarray(outputs, dtype=np.float32)
    num_classes = len(classes)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.shape[1] != 4 + num_classes and (
        arr.shape[0] == 4 + num_classes
        or (arr.shape[0] < arr.shape[1] and arr.shape[0] <= 4 + 1000)
        or arr.shape[1] < 4 + num_classes
    ):
        arr = arr.T

    if arr.shape[0] and float(arr[:, :4].max()) > 1.5:
        arr = arr.copy()
        arr[:, :4] /= input_size

    class_scores = arr[:, 4:]
    scores = class_scores.max(axis=1)
    class_ids = class_scores.argmax(axis=1)

    # ---- [DETECT][RAW/FILTER/CLASS/CLASS_MAP] observability ----------------
    # Logs network candidates above a logging floor (0.02) BEFORE the config
    # confidence filter, so a detection that YOLO sees but the threshold drops
    # is never hidden. Purely observational: `keep` and the return value are
    # untouched. `dbg()` lines go only to logs/detection_debug.log; rejection
    # events are echoed to the console too.
    inv_scale = 1.0 / scale if scale != 0 else 1.0
    offset_x = dx * inv_scale
    offset_y = dy * inv_scale
    _cand = np.where(scores >= 0.02)[0][:300]
    for ci in np.atleast_1d(_cand):
        c = int(ci)
        cid = int(class_ids[c])
        s = float(scores[c])
        cx = float(arr[c, 0]) * input_size * inv_scale
        cy = float(arr[c, 1]) * input_size * inv_scale
        hw = float(arr[c, 2]) * input_size * 0.5 * inv_scale
        hh = float(arr[c, 3]) * input_size * 0.5 * inv_scale
        bx1 = int(np.clip(round(cx - hw - offset_x), 0, frame_width))
        by1 = int(np.clip(round(cy - hh - offset_y), 0, frame_height))
        bx2 = int(np.clip(round(cx + hw - offset_x), 0, frame_width))
        by2 = int(np.clip(round(cy + hh - offset_y), 0, frame_height))
        if cid >= num_classes:
            detect_log.dbg("CLASS", f"class_id={cid} class_name=unknown conf={s:.2f} bbox=({bx1},{by1},{bx2},{by2})")
            detect_log.dbg("CLASS_MAP", f"source={cid} mapped_to=None(dropped, outside class range {num_classes})")
            detect_log.bump("unknown")
            continue
        name = classes[cid]
        detect_log.dbg(
            "RAW",
            f"class_id={cid} class={name} conf={s:.2f} bbox=({bx1},{by1},{bx2},{by2}) "
            f"center=({(bx1 + bx2) // 2},{(by1 + by2) // 2}) w={bx2 - bx1} h={by2 - by1}",
        )
        detect_log.bump("raw")
        if s < conf_threshold:
            detect_log.dbg_info(
                "FILTER", f"reason=confidence class={name} conf={s:.2f} threshold={conf_threshold:.2f}"
            )
            detect_log.bump("rejected_confidence")
        else:
            detect_log.dbg("FILTER", f"ACCEPT class={name} conf={s:.2f}")
            detect_log.bump("accepted")
    if len(_cand) >= 300:
        detect_log.dbg("RAW", f"raw_truncated=true (first 300 of {len(scores)} candidates logged)")

    keep = scores >= conf_threshold
    keep &= class_ids < num_classes
    if not keep.any():
        return []

    rows = arr[keep]
    scores = scores[keep]
    class_ids = class_ids[keep]

    inv_scale = 1.0 / scale if scale != 0 else 1.0
    offset_x = dx * inv_scale
    offset_y = dy * inv_scale
    half_w = rows[:, 2] * input_size * 0.5 * inv_scale
    half_h = rows[:, 3] * input_size * 0.5 * inv_scale
    cx = rows[:, 0] * input_size * inv_scale
    cy = rows[:, 1] * input_size * inv_scale
    x1 = cx - half_w - offset_x
    y1 = cy - half_h - offset_y
    x2 = cx + half_w - offset_x
    y2 = cy + half_h - offset_y
    x1 = np.clip(np.round(x1), 0, frame_width).astype(np.int32)
    y1 = np.clip(np.round(y1), 0, frame_height).astype(np.int32)
    x2 = np.clip(np.round(x2), 0, frame_width).astype(np.int32)
    y2 = np.clip(np.round(y2), 0, frame_height).astype(np.int32)
    widths = x2 - x1
    heights = y2 - y1
    valid = (widths > 0) & (heights > 0)
    if not valid.any():
        return []

    x1, y1, x2, y2, scores_v, cids = x1[valid], y1[valid], x2[valid], y2[valid], scores[valid], class_ids[valid]
    label_names = [classes[int(c)] for c in cids]

    selected: list[tuple[int, float, str]] = []
    by_label: dict[str, list[tuple[int, float]]] = {}
    for idx in range(len(x1)):
        by_label.setdefault(label_names[idx], []).append((idx, float(scores_v[idx])))
    for label, items in by_label.items():
        box_tuples = [(int(x1[i]), int(y1[i]), int(x2[i] - x1[i]), int(y2[i] - y1[i])) for i, _ in items]
        score_list = [s for _, s in items]
        indices = cv2.dnn.NMSBoxes(box_tuples, score_list, conf_threshold, iou_threshold)
        if indices is None or len(indices) == 0:
            suppress = len(items)
            if suppress:
                detect_log.dbg("NMS", f"class={label} suppressed={suppress} (all overlapping duplicates)")
            continue
        suppress = len(items) - len(indices)
        if suppress:
            detect_log.dbg("NMS", f"class={label} suppressed={suppress} (overlapping duplicates)")
        for i in np.atleast_1d(indices):
            orig_idx = items[int(i)][0]
            selected.append((orig_idx, float(scores_v[orig_idx]), label))

    selected.sort(key=lambda item: item[1], reverse=True)
    return [
        ObjectDetection(
            class_name=label,
            confidence=conf,
            bounding_box=Box(x=int(x1[orig_idx]), y=int(y1[orig_idx]),
                             width=int(x2[orig_idx] - x1[orig_idx]),
                             height=int(y2[orig_idx] - y1[orig_idx])),
            timestamp=0,
        )
        for orig_idx, conf, label in selected
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
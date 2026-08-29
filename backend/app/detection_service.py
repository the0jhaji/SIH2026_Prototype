"""DetectionService: runs a local object detector over the camera feed.

Inference happens on its own daemon thread so ONNX/CV work can never stall the
camera capture thread, the JPEG encoder, or the event loop. It polls the
camera manager for *new* frames (by frame id), runs the detector, and keeps
the latest result plus a health status for the REST endpoints.

Disabled mode is fully inert — no import of ``ai``, no thread — so the app
boots identically whether detection is on or off.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("basai.detection")

# Make the repo root importable so `ai.detection` resolves from the backend venv.
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _now_ms() -> int | None:
    return int(time.time() * 1000)


class DetectionService:
    """Owns the detector thread and exposes ``status()`` / ``latest()`` payloads."""

    def __init__(
        self,
        camera,
        detector=None,
        *,
        enabled: bool = False,
        kind: str = "mock",
        model_path: str | None = None,
        conf_threshold: float = 0.5,
        poll_ms: int = 100,
    ) -> None:
        self._camera = camera
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._enabled = enabled and (detector is not None or kind in {"mock", "yolo"})
        self._kind = kind
        self._model_path = model_path
        self._conf_threshold = conf_threshold
        self._poll_ms = max(10, poll_ms)
        self._detector = detector
        self._last_inference_ms: Optional[int] = None
        self._inference_ms: Optional[int] = None
        self._detections: list[dict] = []
        self._frame_size: tuple[int, int] | None = None
        self._last_error: Optional[str] = None
        if self._enabled:
            self._bootstrap()

    # ------------------------------------------------------------- lifecycle

    def _bootstrap(self) -> None:
        """Create the detector from config if none was injected, then start the
        worker thread. Failures are recorded as an ERROR status — never raised."""
        if self._detector is None:
            try:
                from ai.detection.detector import create_detector

                self._detector = create_detector(
                    self._kind,
                    model_path=self._model_path,
                    conf_threshold=self._conf_threshold,
                )
            except Exception as exc:  # noqa: BLE001 - surface via status
                logger.exception("Detection backend unavailable")
                with self._lock:
                    self._last_error = f"Detection backend unavailable: {exc}"
                self._enabled = False
                return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="basai-detection",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the worker thread. Idempotent; safe at server shutdown."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    close = stop

    # ------------------------------------------------------------------ loop

    def _run(self) -> None:
        last_id = -1
        while not self._stop.is_set():
            try:
                last_id = self._infer_once(last_id)
            except Exception as exc:  # noqa: BLE001 - keep the loop resilient
                logger.exception("Detection inference failed")
                with self._lock:
                    self._last_error = f"Detection failed: {exc}"
            self._stop.wait(self._poll_ms / 1000.0)

    def _infer_once(self, last_id: int) -> int:
        cap = self._camera.latest_capture()
        if cap is None or cap[0] == last_id:
            return last_id
        frame_id, frame = cap
        started = time.perf_counter()
        dets = self._detector.detect(frame)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        with self._lock:
            self._last_error = None
            self._last_inference_ms = _now_ms()
            self._inference_ms = elapsed_ms
            self._detections = [d.to_dict() for d in dets]
            self._frame_size = (frame.shape[1], frame.shape[0])
        return frame_id

    # --------------------------------------------------------------- access

    def is_enabled(self) -> bool:
        return self._enabled

    def status(self) -> dict:
        if not self._enabled:
            return {
                "enabled": False,
                "detector": None,
                "modelLoaded": False,
                "modelPath": None,
                "classes": None,
                "inferenceStatus": "disabled",
                "lastInference": None,
                "detectionCount": 0,
                "error": None,
            }
        det = self._detector
        with self._lock:
            last_inf = self._last_inference_ms
            error = self._last_error
            count = len(self._detections)
        det_status = det.status() if det is not None else None
        return {
            "enabled": True,
            "detector": det_status.detector_type if det_status else self._kind,
            "modelLoaded": bool(det_status and det_status.model_loaded),
            "modelPath": det_status.model_path if det_status else None,
            "classes": list(det_status.classes) if det_status else None,
            "inferenceStatus": "error" if error else ("ok" if last_inf is not None else "idle"),
            "lastInference": last_inf,
            "detectionCount": count,
            "error": error,
        }

    def latest(self) -> dict:
        with self._lock:
            dets = list(self._detections)
            frame_size = self._frame_size
            last_inf = self._last_inference_ms
            inference_ms = self._inference_ms
            error = self._last_error
        return {
            "enabled": self._enabled,
            "frameWidth": frame_size[0] if frame_size else None,
            "frameHeight": frame_size[1] if frame_size else None,
            "detections": dets,
            "lastInferenceMs": last_inf,
            "inferenceMs": inference_ms,
            "inferenceStatus": "error" if error else ("ok" if last_inf is not None else "idle"),
            "error": error,
        }
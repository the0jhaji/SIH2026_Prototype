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
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .detection_tracker import TemporalTracker
from ai.detection import detect_log

logger = logging.getLogger("astraai.detection")

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
        general_model_path: str | None = None,
        custom_model_path: str | None = None,
        conf_threshold: float = 0.5,
        poll_ms: int = 100,
        target_fps: float = 0.0,
        trace: bool = False,
        scene: str | None = None,
        cv_threads: int | None = None,
        debounce_frames: int = 2,
        ema_alpha: float = 0.35,
        unknown_enabled: bool = True,
        unknown_min_area: float = 0.004,
        unknown_overlap_iou: float = 0.35,
        unknown_motion_threshold: int = 25,
    ) -> None:
        self._camera = camera
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._enabled = enabled and (detector is not None or kind in {"mock", "yolo", "dual", "heuristic"})
        self._kind = kind
        self._model_path = model_path
        self._general_model_path = general_model_path
        self._custom_model_path = custom_model_path
        self._conf_threshold = conf_threshold
        self._poll_ms = max(10, poll_ms)
        self._target_fps = max(0.0, float(target_fps or 0.0))
        self._trace = bool(trace)
        self._next_due = 0.0
        self._inference_count = 0
        self._skipped_for_rate = 0
        self._fps_window_started = time.perf_counter()
        self._fps_window_count = 0
        self._actual_fps = 0.0
        self._scene = scene
        self._cv_threads = cv_threads
        self._detector = detector
        self._generic = None
        self._unknown_enabled = unknown_enabled
        self._unknown_min_area = unknown_min_area
        self._unknown_overlap_iou = unknown_overlap_iou
        self._unknown_motion_threshold = unknown_motion_threshold
        self._tracker = TemporalTracker(debounce_frames=debounce_frames, alpha_conf=ema_alpha, alpha_box=ema_alpha)
        self._last_inference_ms: Optional[int] = None
        self._inference_ms: Optional[int] = None
        self._detections: list[dict] = []
        self._raw_detections: list[dict] = []
        self._unknown_detections: list[dict] = []
        self._raw_unknown_detections: list[dict] = []
        self._frame_size: tuple[int, int] | None = None
        self._last_error: Optional[str] = None
        self._dbg_last_summary = time.perf_counter()
        self._dbg_last_state: tuple[int, int] | None = None
        if self._enabled:
            self._bootstrap()

    # ------------------------------------------------------------- lifecycle

    def _bootstrap(self) -> None:
        """Create the detector from config if none was injected, then start the
        worker thread. Failures are recorded as an ERROR status — never raised."""
        detect_log.set_enabled(self._trace)
        if self._detector is None:
            try:
                from ai.detection.detector import create_detector

                self._detector = create_detector(
                    self._kind,
                    model_path=self._model_path,
                    general_model_path=self._general_model_path,
                    custom_model_path=self._custom_model_path,
                    conf_threshold=self._conf_threshold,
                    scene=self._scene,
                    cv_threads=self._cv_threads,
                )
            except Exception as exc:  # noqa: BLE001 - surface via status
                logger.exception("Detection backend unavailable")
                with self._lock:
                    self._last_error = f"Detection backend unavailable: {exc}"
                self._enabled = False
                return
        if self._unknown_enabled:
            try:
                from ai.detection.generic import GenericProposalDetector

                self._generic = GenericProposalDetector(
                    conf_threshold=self._conf_threshold,
                    min_area=self._unknown_min_area,
                    motion_threshold=self._unknown_motion_threshold,
                )
            except Exception as exc:  # noqa: BLE001 - unknown objects are best-effort
                logger.warning("Unknown-object detector unavailable: %s", exc)
                self._generic = None
        det_st = self._detector.status()
        logger.info(
            "Loaded detection model:\n  path=%s\n  type=%s\n  modelLoaded=%s\n  classes(%d): %s",
            det_st.model_path,
            det_st.detector_type,
            det_st.model_loaded,
            len(det_st.classes),
            ", ".join(f"{i} {c}" for i, c in enumerate(det_st.classes)),
        )
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="astraai-detection",
            daemon=True,
        )
        self._boost_thread_priority(self._thread)
        self._thread.start()

    @staticmethod
    def _boost_thread_priority(thread: threading.Thread) -> None:
        # Windows "Balanced" power plan parks daemon threads on efficiency cores,
        # measurably ~6x slower YOLO forwards than foreground work. Raise the
        # detector thread's priority so sustained inference stays near real-time.
        if os.name != "nt":
            return
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            THREAD_SET_INFORMATION = 0x0020
            THREAD_PRIORITY_ABOVE_NORMAL = 1
            handle = kernel32.OpenThread(THREAD_SET_INFORMATION, False, thread.native_id)
            if handle:
                try:
                    kernel32.SetThreadPriority(handle, THREAD_PRIORITY_ABOVE_NORMAL)
                finally:
                    kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 - best-effort, never fatal
            pass

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
                detect_log.dbg_error("FAIL", f"inference_error={exc}")
                logger.exception("Detection inference failed")
                with self._lock:
                    self._last_error = f"Detection failed: {exc}"
            # No poll delay: process the next frame immediately.
            # The camera's latest_capture() returns only the newest frame,
            # so idle loops (no new frame) are near-zero cost via the ID check.
            if last_id == -1:
                self._stop.wait(0.01)

    def _infer_once(self, last_id: int) -> int:
        cap = self._camera.latest_capture()
        if cap is None or cap[0] == last_id:
            return last_id
        # Rate gate: always take the NEWEST frame, never a backlog. If the camera
        # produced frames while we were busy, the intermediate ones are dropped on
        # purpose — queuing them would only add latency and inflate the backlog.
        if self._target_fps > 0:
            now = time.perf_counter()
            if now < self._next_due:
                with self._lock:
                    self._skipped_for_rate += 1
                return last_id
            self._next_due = now + (1.0 / self._target_fps)
        frame_id, frame = cap
        started = time.perf_counter()
        detect_log.ensure_setup()
        cam = self._camera_status()
        detect_log.dbg(
            "FRAME",
            f"id={frame_id} size={frame.shape[1]}x{frame.shape[0]} "
            f"fps={cam.get('fps', '?')} camera={cam.get('status', '?')}",
        )
        raw = self._detector.detect(frame)
        unknown_raw: list[Detection] = []
        if self._generic is not None:
            proposals = self._generic.detect(frame)
            # A generic proposal is only a real "unknown" when it does NOT
            # overlap a known-class detection; suppressing here keeps the
            # unknown feed honest (a person is never also "unknown_object").
            for proposal in proposals:
                if self._overlaps_known(proposal, raw):
                    detect_log.dbg_info(
                        "UNKNOWN",
                        f"suppressed label=unknown_object conf={proposal.confidence:.2f} (overlaps known)",
                    )
                    continue
                unknown_raw.append(proposal)
                detect_log.bump("unknown")
                detect_log.dbg(
                    "CLASS_MAP",
                    f"source=generic_motion mapped_to=unknown_object conf={proposal.confidence:.2f}",
                )
                detect_log.dbg_info(
                    "UNKNOWN", f"accepted label=unknown_object conf={proposal.confidence:.2f}"
                )
        stable = self._tracker.update(raw + unknown_raw)
        known_stable = [d for d in stable if d.class_name != "unknown_object"]
        unknown_stable = [d for d in stable if d.class_name == "unknown_object"]
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        detect_log.dbg_info(
            "YOLO",
            f"inference_ms={elapsed_ms} raw_known={len(raw)} raw_unknown={len(unknown_raw)}",
        )
        per_class = {
            d.class_name: round(d.confidence, 2)
            for d in known_stable
        }
        detect_log.dbg_info(
            "FINAL",
            f"stable_known={len(known_stable)} stable_unknown={len(unknown_stable)} "
            f"detail={(', '.join(f'{k}={v}' for k, v in sorted(per_class.items())) or 'none')}",
        )
        with self._lock:
            self._last_error = None
            self._last_inference_ms = _now_ms()
            self._inference_ms = elapsed_ms
            self._raw_detections = [d.to_dict() for d in raw]
            self._detections = [d.to_dict() for d in known_stable]
            self._raw_unknown_detections = [d.to_dict() for d in unknown_raw]
            self._unknown_detections = [d.to_dict() for d in unknown_stable]
            self._frame_size = (frame.shape[1], frame.shape[0])
            self._inference_count += 1
            self._fps_window_count += 1
            window = time.perf_counter() - self._fps_window_started
            if window >= 1.0:
                self._actual_fps = self._fps_window_count / window
                self._fps_window_count = 0
                self._fps_window_started = time.perf_counter()
        self._maybe_summary()
        self._dbg_state_change()
        return frame_id

    def _camera_status(self) -> dict:
        """Snapshot the camera info dict guarded — tests inject stub cameras."""
        try:
            info = self._camera.info()
            return {"status": info.get("status"), "fps": info.get("fps")}
        except Exception:  # noqa: BLE001 - best-effort diagnostics
            return {}

    def _maybe_summary(self) -> None:
        """Roll a once-per-second detection summary from the stage counters."""
        now = time.perf_counter()
        dt = now - self._dbg_last_summary
        if dt < 1.0:
            return
        self._dbg_last_summary = now
        counters = detect_log.take_counters()
        detect_log.dbg_info(
            "SUMMARY",
            f"window_s={dt:.1f} infer_rate={1.0 / dt:.1f} fps "
            f"raw={counters['raw']} accepted={counters['accepted']} "
            f"rejected_confidence={counters['rejected_confidence']} unknown={counters['unknown']}",
        )

    def _dbg_state_change(self) -> None:
        """Emit STATE_CHANGE only when the stable feed actually changes."""
        with self._lock:
            new = (len(self._detections), len(self._unknown_detections))
        if new == self._dbg_last_state:
            return
        self._dbg_last_state = new
        detect_log.dbg_info("STATE_CHANGE", f"known={new[0]} unknown={new[1]}")

    def _overlaps_known(self, proposal: Detection, known: list) -> bool:
        """Suppress a generic proposal that collides with a known detection.

        Matches either by IoU above the configured floor or by containment
        (the proposal's centre inside a known box / known centre inside the
        proposal) — same matching style the temporal tracker uses.
        """
        iou_floor = self._unknown_overlap_iou
        bx1, by1, bx2, by2 = proposal.x1, proposal.y1, proposal.x2, proposal.y2
        px, py = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
        for known_det in known:
            kx1, ky1, kx2, ky2 = known_det.x1, known_det.y1, known_det.x2, known_det.y2
            kcx, kcy = (kx1 + kx2) / 2.0, (ky1 + ky2) / 2.0
            inside = (kx1 <= px <= kx2 and ky1 <= py <= ky2) or (
                bx1 <= kcx <= bx2 and by1 <= kcy <= by2
            )
            if inside:
                return True
            ix = max(0.0, min(bx2, kx2) - max(bx1, kx1))
            iy = max(0.0, min(by2, ky2) - max(by1, ky1))
            inter = ix * iy
            if inter <= 0.0:
                continue
            union = (bx2 - bx1) * (by2 - by1) + (kx2 - kx1) * (ky2 - ky1) - inter
            if inter / union >= iou_floor:
                return True
        return False

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
                "confThreshold": self._conf_threshold,
                "unknownEnabled": self._unknown_enabled,
                "unknownMode": None,
                "inferenceStatus": "disabled",
                "lastInference": None,
                "detectionCount": 0,
                "rawDetectionCount": 0,
                "unknownCount": 0,
                "unknownDetections": [],
                "rawUnknownDetections": [],
                "inferenceMs": None,
                "error": None,
                **self._rate_payload(),
            }
        det = self._detector
        with self._lock:
            last_inf = self._last_inference_ms
            error = self._last_error
            count = len(self._detections)
            raw_count = len(self._raw_detections)
            unknown_count = len(self._unknown_detections)
            unknown = list(self._unknown_detections)
            raw_unknown = list(self._raw_unknown_detections)
            rates = self._rate_payload()
        det_status = det.status() if det is not None else None
        return {
            "enabled": True,
            "detector": det_status.detector_type if det_status else self._kind,
            "modelLoaded": bool(det_status and det_status.model_loaded),
            "modelPath": det_status.model_path if det_status else None,
            "classes": list(det_status.classes) if det_status else None,
            "confThreshold": self._conf_threshold,
            "unknownEnabled": self._generic is not None,
            "unknownMode": self._generic.mode if self._generic is not None else None,
            "inferenceStatus": "error" if error else ("ok" if last_inf is not None else "idle"),
            "lastInference": last_inf,
            "inferenceMs": self._inference_ms,
            "detectionCount": count,
            "rawDetectionCount": raw_count,
            "unknownCount": unknown_count,
            "unknownDetections": unknown,
            "rawUnknownDetections": raw_unknown,
            "error": error,
            **rates,
        }

    def _rate_payload(self) -> dict:
        """Honest rate telemetry: what was asked for vs what the host achieved."""
        return {
            "targetFps": self._target_fps,
            "actualFps": round(self._actual_fps, 2),
            "inferenceCount": self._inference_count,
            "skippedForRate": self._skipped_for_rate,
            "traceEnabled": self._trace,
        }

    def latest(self) -> dict:
        with self._lock:
            dets = list(self._detections)
            raw = list(self._raw_detections)
            unknown = list(self._unknown_detections)
            raw_unknown = list(self._raw_unknown_detections)
            frame_size = self._frame_size
            last_inf = self._last_inference_ms
            inference_ms = self._inference_ms
            error = self._last_error
            rates = self._rate_payload()
        return {
            "enabled": self._enabled,
            "frameWidth": frame_size[0] if frame_size else None,
            "frameHeight": frame_size[1] if frame_size else None,
            "detections": dets,
            "rawDetections": raw,
            "unknownDetections": unknown,
            "rawUnknownDetections": raw_unknown,
            "lastInferenceMs": last_inf,
            "inferenceMs": inference_ms,
            "inferenceStatus": "error" if error else ("ok" if last_inf is not None else "idle"),
            "error": error,
            **rates,
        }
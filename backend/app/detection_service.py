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


#: A box smaller than the frame minimum in either axis is a degenerate
#: detection rather than an object. Rejected by the overlay, not here: the
#: backend still reports what the model said, the renderer decides what is
#: drawable.


def _clamp_box(payload: dict, frame_w: int, frame_h: int) -> dict:
    """Clamp one detection payload into the detection frame.

    Every consumer treats these numbers as pixels of *this* frame: the
    dashboard overlay (percentage of the image), attendance containment,
    hazard proximity. The EMA tracker only enforces the lower bound, so a
    detector that emits an out-of-range box produced garbage geometry in all
    three places at once. Clamping at the seam fixes it once, for everyone.
    """
    def _px(value, limit: int) -> int:
        try:
            num = int(round(float(value)))
        except (TypeError, ValueError):
            return 0
        return min(max(num, 0), limit)

    return {
        **payload,
        "x1": _px(payload.get("x1"), frame_w),
        "y1": _px(payload.get("y1"), frame_h),
        "x2": _px(payload.get("x2"), frame_w),
        "y2": _px(payload.get("y2"), frame_h),
    }


def _payloads(detections, frame_w: int, frame_h: int) -> list[dict]:
    """Serialize detections to API payloads, clamped to the detection frame."""
    return [_clamp_box(d.to_dict(), frame_w, frame_h) for d in detections]


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
        iou_threshold: float = 0.45,
        poll_ms: int = 100,
        target_fps: float = 0.0,
        trace: bool = False,
        trace_level: str = "DEBUG",
        trace_buffer: int = 200,
        text_log: bool = False,
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
        self._iou_threshold = iou_threshold
        self._poll_ms = max(10, poll_ms)
        self._target_fps = max(0.0, float(target_fps or 0.0))
        self._trace = bool(trace)
        self._trace_level = str(trace_level or "DEBUG")
        self._trace_buffer = int(trace_buffer)
        #: Legacy verbose per-frame file log. Independent of `trace` on purpose:
        #: it is the expensive one, so structured tracing never implies it.
        self._text_log = bool(text_log)
        # Apply the process-wide logging gates here, at construction, not in the
        # worker thread: `detect_log` defaults to on so tests work, which means a
        # service that only configured itself inside `_bootstrap` would let other
        # threads (safety, attendance) record events before the first inference.
        # A *disabled* service stays out of it entirely — it has no opinion about
        # global logging and must not silence a logger another suite is using.
        if self._enabled:
            detect_log.set_enabled(self._text_log)
            detect_log.set_level(self._trace_level if self._trace else "OFF")
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
        self._dbg_last_frame_size: tuple[int, int] | None = None
        if self._enabled:
            self._bootstrap()

    # ------------------------------------------------------------- lifecycle

    def _bootstrap(self) -> None:
        """Create the detector from config if none was injected, then start the
        worker thread. Failures are recorded as an ERROR status — never raised."""
        # The logging gates were already applied in __init__ so no other thread can
        # record before the first inference. A service stopped before it finished
        # booting must also not reconfigure them on its way out: that would
        # resurrect tracing (or the expensive text log) for a service nobody uses.
        if self._stop.is_set():
            return
        if self._trace:
            # Buffer size is process-wide; push it only while tracing so an off
            # service does not shrink a buffer another service is filling.
            detect_log.set_buffer_size(self._trace_buffer)
            detect_log.event(
                "DETECTOR_BOOTSTRAP",
                detector=self._kind,
                unknown_enabled=self._unknown_enabled,
                target_fps=self._target_fps,
                conf_threshold=self._conf_threshold,
            )
            # OpenCLIP classification of unknown tracks is not implemented in this
            # build. Reported once, honestly, so a trace reader can tell "the
            # classifier said nothing" apart from "the classifier never ran" —
            # unknown tracks are reported as unclassified and ASTRA continues.
            detect_log.event(
                "OPENCLIP_UNAVAILABLE",
                reason="classifier_not_installed",
                note="unknown tracks are reported unclassified; detection is unaffected",
            )
        if self._detector is None:
            try:
                from ai.detection.detector import create_detector

                self._detector = create_detector(
                    self._kind,
                    model_path=self._model_path,
                    general_model_path=self._general_model_path,
                    custom_model_path=self._custom_model_path,
                    conf_threshold=self._conf_threshold,
                    iou_threshold=self._iou_threshold,
                    scene=self._scene,
                    cv_threads=self._cv_threads,
                )
            except Exception as exc:  # noqa: BLE001 - surface via status
                logger.exception("Detection backend unavailable")
                with self._lock:
                    self._last_error = f"Detection backend unavailable: {exc}"
                self._enabled = False
                return
        # Load eagerly. YoloDetector resolves its class vocabulary from the
        # `.names` file next to the ONNX *inside* load(); reading status()
        # before that reports the 5-entry DEFAULT_CLASSES placeholder and a
        # null size — i.e. a completely different model than the one in use.
        # The status banner must describe the model that is actually loaded.
        try:
            self._detector.load()
        except Exception as exc:  # noqa: BLE001 - surface via status
            # Do NOT disable here: the caller still needs to see WHICH detector
            # was requested and WHY it has no weights. Disabling would report
            # `detector: null` and hide the real cause behind a silent mock-free
            # idle service. The worker thread retries and keeps the error current.
            logger.exception("Detection weights could not be loaded")
            with self._lock:
                self._last_error = f"Detection weights could not be loaded: {exc}"
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
        classes = list(det_st.classes)
        logger.info(
            "Loaded detection model:\n"
            "  backend        = %s\n"
            "  path           = %s\n"
            "  size           = %s\n"
            "  model_loaded   = %s\n"
            "  class_count    = %d\n"
            "  general_purpose= %s\n"
            "  classes        = %s\n"
            "  input_size     = %s\n"
            "  conf_threshold = %s\n"
            "  iou_threshold  = %s",
            self._kind,
            det_st.model_path,
            f"{det_st.model_size_mb:.2f} MB" if det_st.model_size_mb else "unknown",
            det_st.model_loaded,
            len(classes),
            "yes" if det_st.general_purpose is not False else
            "NO - narrow vocabulary, cannot detect person/bottle/cup/laptop",
            ", ".join(classes) if len(classes) <= 20 else
            f"{', '.join(classes[:20])} ... (+{len(classes) - 20} more)",
            det_st.input_size,
            det_st.conf_threshold if det_st.conf_threshold is not None else self._conf_threshold,
            det_st.iou_threshold,
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
                # ERROR level so a failing pipeline is visible at a low verbosity.
                # `event` never raises, so this cannot become the failure.
                detect_log.event(
                    "DETECTION_FAILED",
                    level=detect_log.TRACE_ERROR,
                    error=str(exc)[:200],
                )
                logger.exception("Detection inference failed")
                with self._lock:
                    self._last_error = f"Detection failed: {exc}"
            # No poll delay: process the next frame immediately.
            # The camera's latest_capture() returns only the newest frame,
            # so idle loops (no new frame) are near-zero cost via the ID check.
            if last_id == -1:
                self._stop.wait(0.01)

    def _infer_once(self, last_id: int) -> int:
        capture_started = time.perf_counter()
        cap = self._camera.latest_capture()
        frame_taken = time.perf_counter()
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
        tracing = detect_log.trace_enabled()
        if tracing:
            # FRAME is sampled, not per-frame: the frame id and size are the only
            # things worth recording, and a new size is the interesting case.
            size = (int(frame.shape[1]), int(frame.shape[0]))
            if size != self._dbg_last_frame_size:
                self._dbg_last_frame_size = size
                detect_log.event(
                    "FRAME_SIZE_CHANGED",
                    frame_width=size[0],
                    frame_height=size[1],
                )
        detect_log.ensure_setup()
        cam = self._camera_status()
        detect_log.dbg(
            "FRAME",
            f"id={frame_id} size={frame.shape[1]}x{frame.shape[0]} "
            f"fps={cam.get('fps', '?')} camera={cam.get('status', '?')}",
        )
        detect_started = time.perf_counter()
        raw = self._detector.detect(frame)
        yolo_ms = (time.perf_counter() - detect_started) * 1000.0
        unknown_raw: list[Detection] = []
        if self._generic is not None:
            unknown_started = time.perf_counter()
            proposals = self._generic.detect(frame)
            unknown_ms = (time.perf_counter() - unknown_started) * 1000.0
            # A generic proposal is only a real "unknown" when it does NOT
            # overlap a known-class detection; suppressing here keeps the
            # unknown feed honest (a person is never also "unknown_object").
            for proposal in proposals:
                if self._overlaps_known(proposal, raw):
                    detect_log.dbg_info(
                        "UNKNOWN",
                        f"suppressed label=unknown_object conf={proposal.confidence:.2f} (overlaps known)",
                    )
                    if tracing:
                        detect_log.event(
                            "UNKNOWN_PROPOSAL_SUPPRESSED",
                            level=detect_log.TRACE_DEBUG,
                            log=False,
                            reason="overlaps_known",
                            confidence=round(proposal.confidence, 4),
                            bbox=[proposal.x1, proposal.y1, proposal.x2, proposal.y2],
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
        else:
            unknown_ms = 0.0
        tracker_started = time.perf_counter()
        stable = self._tracker.update(raw + unknown_raw)
        tracker_ms = (time.perf_counter() - tracker_started) * 1000.0
        known_stable = [d for d in stable if d.class_name != "unknown_object"]
        unknown_stable = [d for d in stable if d.class_name == "unknown_object"]
        if tracing:
            # Per-stage durations, then the total. perf_counter() is ~50ns, so
            # measuring is far cheaper than the inference being measured.
            detect_log.stage("yolo_ms", yolo_ms)
            detect_log.stage("unknown_detector_ms", unknown_ms)
            detect_log.stage("tracker_ms", tracker_ms)
            detect_log.stage("capture_ms", (frame_taken - capture_started) * 1000.0)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        # Total spans capture + rate gate + inference, because that is the wall
        # clock a frame actually costs the pipeline. Measured from
        # `capture_started` (not `started`) so capture_ms + the stages reconcile
        # to total_ms. `elapsed_ms` stays inference-only: it is what the status
        # API reports as inferenceMs, and folding capture into it would quietly
        # overstate how long the model took.
        if tracing:
            detect_log.stage("total_ms", (time.perf_counter() - capture_started) * 1000.0)
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
            self._frame_size = (frame.shape[1], frame.shape[0])
            # Clamp to the frame that was actually analysed. The API contract is
            # "these boxes are pixels of a frameWidth x frameHeight image", and
            # the dashboard scales by exactly those numbers.
            fw, fh = self._frame_size
            self._raw_detections = _payloads(raw, fw, fh)
            self._detections = _payloads(known_stable, fw, fh)
            self._raw_unknown_detections = _payloads(unknown_raw, fw, fh)
            self._unknown_detections = _payloads(unknown_stable, fw, fh)
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
        if detect_log.trace_enabled():
            # Already rate-limited to 1/s by the guard above, so this is a sampled
            # diagnostic rather than a per-frame event.
            with self._lock:
                detections = len(self._detections)
                unknown = len(self._unknown_detections)
                skipped = self._skipped_for_rate
                inference_ms = self._inference_ms
            detect_log.event(
                "PIPELINE_SUMMARY",
                level=detect_log.TRACE_DEBUG,
                log=False,
                window_s=round(dt, 2),
                infer_rate=round(1.0 / dt, 2),
                known=detections,
                unknown=unknown,
                inference_ms=inference_ms,
                skipped_for_rate=skipped,
            )

    def _dbg_state_change(self) -> None:
        """Emit STATE_CHANGE only when the stable feed actually changes.

        Change-only by construction: the counts are compared against the last
        emitted pair, so a static scene emits nothing rather than one line per
        frame. This is the seam that reports DETECTION / UNKNOWN_DETECTION
        without turning the trace into a per-frame log.
        """
        with self._lock:
            new = (len(self._detections), len(self._unknown_detections))
            if new == self._dbg_last_state:
                return
            self._dbg_last_state = new
            known = list(self._detections)
            unknown = list(self._unknown_detections)
            inference_ms = self._inference_ms
            frame_size = self._frame_size
        detect_log.dbg_info("STATE_CHANGE", f"known={new[0]} unknown={new[1]}")
        if not detect_log.trace_enabled():
            return
        # A single event per feed per change: the full box list is already in
        # /api/detections, so the trace carries the identities that matter for
        # debugging (which tracks appeared/disappeared) rather than a per-frame
        # dump of every coordinate.
        detect_log.event(
            "DETECTION",
            known=len(known),
            unknown=len(unknown),
            frame_width=frame_size[0] if frame_size else None,
            frame_height=frame_size[1] if frame_size else None,
            inference_ms=inference_ms,
            classes=",".join(d["class_name"] for d in known) or "none",
        )
        detect_log.event(
            "UNKNOWN_DETECTION",
            unknown=len(unknown),
            instance_ids=",".join(d.get("instance_id") or "?" for d in unknown) or "none",
        )

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

    def trace_state(self) -> dict:
        """The service's own trace configuration.

        Single source of truth for every API surface that reports tracing, so
        ``/api/detection/status`` and ``/api/detection/trace`` can never disagree
        with each other or with the process-wide gate another test may have set.
        """
        return {
            "enabled": self._trace,
            "level": self._trace_level if self._trace else "OFF",
            "buffer": self._trace_buffer,
            # Reported so an operator can tell the cheap structured trace from
            # the expensive legacy per-frame file log.
            "textLog": self._text_log,
        }

    def status(self) -> dict:
        if not self._enabled:
            return {
                "enabled": False,
                "detector": None,
                "modelLoaded": False,
                "modelPath": None,
                "modelSizeMb": None,
                "classCount": None,
                "generalPurpose": None,
                "inputSize": None,
                "iouThreshold": None,
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
        classes = list(det_status.classes) if det_status else None
        return {
            "enabled": True,
            "detector": det_status.detector_type if det_status else self._kind,
            "modelLoaded": bool(det_status and det_status.model_loaded),
            "modelPath": det_status.model_path if det_status else None,
            "modelSizeMb": round(det_status.model_size_mb, 2) if det_status and det_status.model_size_mb else None,
            "classCount": len(classes) if classes is not None else None,
            "generalPurpose": det_status.general_purpose if det_status else None,
            "inputSize": det_status.input_size if det_status else None,
            "iouThreshold": det_status.iou_threshold if det_status else None,
            "classes": classes,
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
            # The level the service was configured with, not the process-wide
            # current one: two services in one process (tests) must not report
            # each other's verbosity.
            "traceLevel": self._trace_level if self._trace else "OFF",
            # The legacy per-frame file log is a separate, much more expensive
            # switch; reporting it separately is the only way an operator can
            # tell which one they are paying for.
            "textLogEnabled": self._text_log,
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
        frame_size, frame_source = self._resolve_frame_size(frame_size)
        return {
            "enabled": self._enabled,
            "frameWidth": frame_size[0] if frame_size else None,
            "frameHeight": frame_size[1] if frame_size else None,
            # Where those dimensions came from, so the dashboard can tell a
            # measured inference frame from the camera's configured request
            # instead of silently rendering against an assumed size.
            "frameSizeSource": frame_source,
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

    def _resolve_frame_size(self, known: tuple[int, int] | None) -> tuple[tuple[int, int] | None, str]:
        """Best available size of the frame detections are expressed in.

        The overlay divides pixel coordinates by these numbers, so a ``None``
        here means "render nothing at all" on the client — the failure mode
        that silently hid the unknown-object boxes. The measured inference
        frame is authoritative and sticky; before the first inference the live
        capture supplies the same answer so the feed is drawable immediately.

        There is deliberately NO fallback to the camera's *configured*
        resolution: with the camera stopped that would report a plausible size
        for a feed nobody is looking at, and every consumer that treats a
        non-null frame size as "a frame is being served" (attendance staleness,
        hazard proximity) would start advancing on a dead camera.
        """
        if known and known[0] > 0 and known[1] > 0:
            return known, "inference"
        if not self._enabled:
            return None, "disabled"
        try:
            capture = self._camera.latest_capture()
        except Exception:  # noqa: BLE001 - never fail the payload on telemetry
            capture = None
        frame = capture[1] if capture is not None else None
        shape = getattr(frame, "shape", None)
        if shape is not None and len(shape) >= 2 and shape[1] > 0 and shape[0] > 0:
            return (int(shape[1]), int(shape[0])), "camera"
        return None, "unknown"

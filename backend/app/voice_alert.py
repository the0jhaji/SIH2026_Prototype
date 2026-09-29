"""Offline voice alert service using pyttsx3 (Windows SAPI5).

Optimizations:
- Explicit lifecycle: NOT_STARTED -> STARTING -> READY | ERROR, driven by
  `start()`, which the experiment engine calls. The worker is NOT spawned from
  `__init__`, because a service that is already talking before anyone asked for
  it cannot report honestly that it has "not started".
- Persistent TTS worker thread (init pyttsx3 once, reuse forever).
- Thread-safe priority queue (CRITICAL > HIGH > WARNING > INFO).
- Detection must never call pyttsx3 directly — always enqueue.
- Cooldown/deduplication per key.
- TTS failure never crashes detection.
- Health/error state exposed.
- Clean shutdown.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

logger = logging.getLogger("astraai.voice")

try:
    import pyttsx3  # type: ignore[import-untyped]
    _TTS_AVAILABLE = True
except ImportError:
    pyttsx3 = None  # type: ignore[assignment]
    _TTS_AVAILABLE = False

_PRIORITY_MAP = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3}

# The four states the UI is allowed to render. Anything else must be mapped
# onto one of these before it reaches a client, so the dashboard never invents
# or has to invent a label.
VOICE_NOT_STARTED = "NOT_STARTED"
VOICE_STARTING = "STARTING"
VOICE_READY = "READY"
VOICE_ERROR = "ERROR"

VOICE_STATES = (VOICE_NOT_STARTED, VOICE_STARTING, VOICE_READY, VOICE_ERROR)


class _AlertItem:
    __slots__ = ("message", "key", "priority", "enqueued_at")

    def __init__(self, message: str, key: str, priority: int) -> None:
        self.message = message
        self.key = key
        self.priority = priority
        self.enqueued_at = time.monotonic()

    def __lt__(self, other: "_AlertItem") -> bool:
        return self.priority < other.priority


class VoiceAlertService:
    """Speaks alerts aloud via a persistent background TTS worker.

    The worker is started explicitly by `start()` so that the reported state
    always reflects a real TTS initialisation, not the mere construction of
    this object.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        rate: int = 160,
        volume: float = 1.0,
        cooldown_s: float = 3.0,
        max_queue: int = 20,
    ) -> None:
        self._configured = enabled
        self._enabled = False
        self._rate = rate
        self._volume = volume
        self._cooldown_s = cooldown_s
        self._queue: queue.Queue[_AlertItem] = queue.Queue(maxsize=max_queue)
        self._dedup: dict[str, float] = {}
        self._dedup_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._engine = None
        self._state = VOICE_NOT_STARTED
        self._error: Optional[str] = None
        self._error_count = 0

    # --- lifecycle ---------------------------------------------------------

    def start(self, timeout: float = 5.0) -> dict:
        """Start the TTS worker and wait for it to actually initialise.

        Idempotent. Returns the resulting status so a caller can report the
        real outcome instead of assuming success.
        """
        with self._lifecycle_lock:
            if not self._configured:
                self._state = VOICE_ERROR
                self._error = "voice disabled by configuration (VOICE_ENABLED=false)"
                return self.status()
            if not _TTS_AVAILABLE:
                self._state = VOICE_ERROR
                self._error = "pyttsx3 is not installed in the backend venv"
                return self.status()
            if self._state in (VOICE_STARTING, VOICE_READY) and self._worker is not None:
                if self._worker.is_alive():
                    return self.status()
            self._stop.clear()
            self._state = VOICE_STARTING
            self._error = None
            self._start_worker()

        # Wait for the real init so STARTING -> READY|ERROR is observable
        # rather than a state the UI can only ever guess about.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lifecycle_lock:
                if self._state in (VOICE_READY, VOICE_ERROR):
                    return self.status()
            time.sleep(0.02)
        with self._lifecycle_lock:
            if self._state == VOICE_STARTING:
                self._state = VOICE_ERROR
                self._error = f"pyttsx3 did not initialise within {timeout:.1f}s"
                self._enabled = False
        return self.status()

    def _start_worker(self) -> None:
        def _worker() -> None:
            try:
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", self._rate)
                self._engine.setProperty("volume", self._volume)
                with self._lifecycle_lock:
                    self._state = VOICE_READY
                    self._error = None
                    self._enabled = True
                logger.info("Voice worker started")
            except Exception as exc:  # noqa: BLE001 - reported, never raised
                logger.warning("pyttsx3 init failed — voice in ERROR", exc_info=True)
                with self._lifecycle_lock:
                    self._state = VOICE_ERROR
                    self._error = f"{type(exc).__name__}: {exc}"
                    self._enabled = False
                return

            while not self._stop.is_set():
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is None:
                    break
                # Check dedup
                now = time.monotonic()
                with self._dedup_lock:
                    last = self._dedup.get(item.key, 0.0)
                    if now - last < self._cooldown_s:
                        continue
                    self._dedup[item.key] = now
                # Speak (may block briefly)
                try:
                    self._engine.say(item.message)
                    self._engine.runAndWait()
                    time.sleep(0.05)
                except RuntimeError as exc:
                    if "run loop" in str(exc).lower():
                        try:
                            self._engine = pyttsx3.init()
                            self._engine.setProperty("rate", self._rate)
                            self._engine.setProperty("volume", self._volume)
                        except Exception:  # noqa: BLE001
                            logger.warning("pyttsx3 reinit failed", exc_info=True)
                            with self._lifecycle_lock:
                                self._state = VOICE_ERROR
                                self._error = "pyttsx3 reinit failed"
                                self._enabled = False
                            return
                    else:
                        self._error_count += 1
                        with self._lifecycle_lock:
                            self._error = f"speak failed ({item.message[:60]}): {exc}"
                        logger.warning("Voice speak failed: %s", item.message, exc_info=True)
                except Exception as exc:  # noqa: BLE001
                    self._error_count += 1
                    with self._lifecycle_lock:
                        self._error = f"speak failed: {type(exc).__name__}: {exc}"
                    logger.warning("Voice speak failed: %s", item.message, exc_info=True)

            try:
                self._engine.stop()
            except Exception:  # noqa: BLE001
                pass
            logger.info("Voice worker stopped")

        self._worker = threading.Thread(target=_worker, name="voice-tts", daemon=True)
        self._worker.start()

    def speak(self, message: str, *, key: Optional[str] = None, priority: str = "INFO") -> None:
        """Enqueue a message for TTS. Non-blocking."""
        if self._state != VOICE_READY or not message:
            return
        dedup_key = key or message
        prio = _PRIORITY_MAP.get(priority.upper(), 3)
        item = _AlertItem(message, dedup_key, prio)
        queued = True
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            logger.debug("Voice queue full, dropping: %s", message)
            queued = False
        # Spoken output is the last link of the alert chain, so a trace reader can
        # confirm the operator was actually told. `queued` matters: a dropped
        # prompt is exactly the kind of thing that looks fine in the UI.
        from ai.detection import detect_log

        detect_log.event(
            "VOICE_SPOKEN" if queued else "VOICE_DROPPED",
            level=detect_log.TRACE_INFO,
            instance_id=key,
            message=message[:160],
            priority=priority.upper(),
            queue_depth=self._queue.qsize(),
        )

    def speak_info(self, message: str, *, key: Optional[str] = None) -> None:
        """Queue an informational prompt without blocking perception."""
        self.speak(message, key=key, priority="INFO")

    def speak_warning(self, message: str, *, key: Optional[str] = None) -> None:
        """Queue a corrective warning with higher priority than information."""
        self.speak(message, key=key, priority="WARNING")

    def speak_critical(self, message: str, *, key: Optional[str] = None) -> None:
        """Queue an escalating critical prompt."""
        self.speak(message, key=key, priority="CRITICAL")

    # --- hazard/safety alerts ---

    def speak_hazard(self, hazard_type: str, risk_level: str, object_name: str) -> None:
        severity_to_priority = {"CRITICAL": "CRITICAL", "WARNING": "WARNING", "CAUTION": "INFO"}
        prio = severity_to_priority.get(risk_level, "INFO")
        msg_map = {
            "CRITICAL": f"Critical hazard. {object_name} detected.",
            "WARNING": f"Warning. {hazard_type} detected. {object_name}.",
            "CAUTION": f"Caution. {hazard_type} detected.",
        }
        self.speak(msg_map.get(risk_level, f"Alert. {hazard_type}."), key=f"hazard:{object_name}:{hazard_type}", priority=prio)

    def speak_emergency(self, event_type: str, description: str) -> None:
        self.speak(
            f"Emergency. {description}.",
            key=f"emergency:{event_type}",
            priority="CRITICAL",
        )

    # --- experiment lifecycle (backward compat) ---

    def announce_experiment_started(self, experiment_name: str) -> None:
        self.speak(f"Experiment started. {experiment_name}.", key="experiment_started")

    def announce_next_step(self, step_label: str, step_number: int, total: int) -> None:
        self.speak(f"Next step {step_number} of {total}. {step_label}.", key=f"next_step_{step_number}")

    def announce_step_completed(self, step_label: str) -> None:
        self.speak(f"Step completed. {step_label}.", key=f"completed_{step_label}")

    def announce_skipped_step(self, expected_label: str) -> None:
        self.speak(f"Warning. The expected step was skipped. {expected_label}.", key="skipped", priority="WARNING")

    def announce_out_of_sequence(self, expected_label: str) -> None:
        self.speak_warning(
            f"Warning. Activity is out of sequence. Expected: {expected_label}.",
            key="out_of_sequence",
        )

    def announce_wrong_object(self, expected_label: str, observed_label: str) -> None:
        self.speak_warning(
            f"Warning. {expected_label} is expected, not {observed_label}.",
            key=f"wrong_object:{expected_label}",
        )

    def announce_wrong_sequence(self, expected_label: str) -> None:
        self.speak_warning(
            f"Warning. Wrong sequence. Expected: {expected_label}.",
            key=f"wrong_sequence:{expected_label}",
        )

    def announce_recovery(self, expected_label: str, *, critical: bool = False) -> None:
        message = f"{'Critical. ' if critical else ''}Return to {expected_label} before continuing."
        if critical:
            self.speak_critical(message, key="recovery_critical")
        else:
            self.speak_warning(message, key="recovery_warning")

    def announce_repeated_step(self, step_label: str) -> None:
        self.speak(f"Step repeated. {step_label}.", key="repeated")

    def announce_uncertain(self) -> None:
        self.speak_warning(
            "Unable to confidently identify the current activity. Please hold the pose and repeat.",
            key="uncertain",
        )

    def announce_experiment_completed(self) -> None:
        self.speak("Experiment completed successfully.", key="experiment_completed")

    def announce_experiment_paused(self) -> None:
        self.speak("Experiment paused. Camera or detection unavailable.", key="experiment_paused")

    # --- health/shutdown ---

    @property
    def state(self) -> str:
        """One of the four VOICE_STATES the UI is allowed to render."""
        return self._state

    @property
    def health(self) -> str:
        # Kept for existing callers; the state vocabulary is now the honest one
        # ("initializing" was not a state, it was a guess about the future).
        return self._state

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def status(self) -> dict:
        """Full lifecycle status. `state` is one of VOICE_STATES, always."""
        return {
            "state": self._state,
            "ready": self._state == VOICE_READY,
            "error": self._error,
            "queueSize": self.queue_size,
            "errorCount": self._error_count,
            "ttsAvailable": _TTS_AVAILABLE,
            "configured": self._configured,
        }

    def close(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        worker = self._worker
        if worker is not None and worker.is_alive():
            # `is_alive()` first: a worker assigned by a concurrent `start()`
            # but not yet begun raises on join, and shutdown must not raise.
            worker.join(timeout=2.0)
        self._enabled = False
        self._worker = None
        with self._lifecycle_lock:
            self._state = VOICE_NOT_STARTED

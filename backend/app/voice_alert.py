"""Offline voice alert service using pyttsx3 (Windows SAPI5).

Phase 5 optimizations:
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
    """Speaks alerts aloud via a persistent background TTS worker."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        rate: int = 160,
        volume: float = 1.0,
        cooldown_s: float = 3.0,
        max_queue: int = 20,
    ) -> None:
        self._enabled = enabled and _TTS_AVAILABLE
        self._rate = rate
        self._volume = volume
        self._cooldown_s = cooldown_s
        self._queue: queue.Queue[_AlertItem] = queue.Queue(maxsize=max_queue)
        self._dedup: dict[str, float] = {}
        self._dedup_lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._engine = None
        self._health = "initializing"
        self._error_count = 0

        if self._enabled:
            self._start_worker()

    def _start_worker(self) -> None:
        def _worker() -> None:
            try:
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", self._rate)
                self._engine.setProperty("volume", self._volume)
                self._health = "ok"
                logger.info("Voice worker started")
            except Exception:
                logger.warning("pyttsx3 init failed — voice disabled", exc_info=True)
                self._health = "init_failed"
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
                    self._health = "ok"
                    time.sleep(0.05)
                except RuntimeError as exc:
                    if "run loop" in str(exc).lower():
                        try:
                            self._engine = pyttsx3.init()
                            self._engine.setProperty("rate", self._rate)
                            self._engine.setProperty("volume", self._volume)
                        except Exception:
                            logger.warning("pyttsx3 reinit failed", exc_info=True)
                            self._health = "reinit_failed"
                            self._enabled = False
                            return
                    else:
                        self._error_count += 1
                        self._health = f"error_{self._error_count}"
                        logger.warning("Voice speak failed: %s", item.message, exc_info=True)
                except Exception:
                    self._error_count += 1
                    self._health = f"error_{self._error_count}"
                    logger.warning("Voice speak failed: %s", item.message, exc_info=True)

            try:
                self._engine.stop()
            except Exception:
                pass
            logger.info("Voice worker stopped")

        self._worker = threading.Thread(target=_worker, name="voice-tts", daemon=True)
        self._worker.start()

    def speak(self, message: str, *, key: Optional[str] = None, priority: str = "INFO") -> None:
        """Enqueue a message for TTS. Non-blocking."""
        if not self._enabled or not message:
            return
        dedup_key = key or message
        prio = _PRIORITY_MAP.get(priority.upper(), 3)
        item = _AlertItem(message, dedup_key, prio)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            logger.debug("Voice queue full, dropping: %s", message)

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
    def health(self) -> str:
        return self._health

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def close(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self._enabled = False

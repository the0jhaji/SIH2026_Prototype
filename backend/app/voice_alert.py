"""Offline voice alert service using pyttsx3 (Windows SAPI5).

Thread-safe: ``speak()`` dispatches to a background thread so the AI
inference loop is never blocked.  Deduplication suppresses identical
messages within a configurable cooldown window.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("astraai.voice")

# pyttsx3 is optional — headless / CI environments get a silent fallback.
try:
    import pyttsx3  # type: ignore[import-untyped]

    _TTS_AVAILABLE = True
except ImportError:
    pyttsx3 = None  # type: ignore[assignment]
    _TTS_AVAILABLE = False


class VoiceAlertService:
    """Speaks experiment lifecycle events aloud with deduplication."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        rate: int = 160,
        volume: float = 1.0,
        cooldown_s: float = 3.0,
    ) -> None:
        self._enabled = enabled and _TTS_AVAILABLE
        self._rate = rate
        self._volume = volume
        self._cooldown_s = cooldown_s
        self._engine = None
        self._lock = threading.Lock()
        self._last_spoken: dict[str, float] = {}
        self._thread: Optional[threading.Thread] = None

        if self._enabled:
            try:
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", self._rate)
                self._engine.setProperty("volume", self._volume)
                logger.info("Voice alert service initialised (pyttsx3)")
            except Exception:  # noqa: BLE001
                logger.warning("pyttsx3 init failed — voice disabled", exc_info=True)
                self._enabled = False

    # ------------------------------------------------------------------ core

    def speak(self, message: str, *, key: Optional[str] = None) -> None:
        """Speak *message* in a background thread.

        If *key* is provided and the same key was spoken within the cooldown
        window the call is silently ignored.
        """
        if not self._enabled or not message:
            return
        dedup_key = key or message
        now = time.monotonic()
        with self._lock:
            last = self._last_spoken.get(dedup_key, 0.0)
            if now - last < self._cooldown_s:
                return
            self._last_spoken[dedup_key] = now
        self._dispatch(message)

    def _dispatch(self, message: str) -> None:
        def _run() -> None:
            try:
                with self._lock:
                    if self._engine is not None:
                        self._engine.say(message)
                        self._engine.runAndWait()
            except Exception:  # noqa: BLE001
                logger.warning("Voice speak failed: %s", message, exc_info=True)

        t = threading.Thread(target=_run, name="voice-tts", daemon=True)
        t.start()

    # -------------------------------------------------------- high-level API

    def announce_experiment_started(self, experiment_name: str) -> None:
        self.speak(
            f"Experiment started. {experiment_name}.",
            key="experiment_started",
        )

    def announce_next_step(self, step_label: str, step_number: int, total: int) -> None:
        self.speak(
            f"Next step {step_number} of {total}. {step_label}.",
            key=f"next_step_{step_number}",
        )

    def announce_step_completed(self, step_label: str) -> None:
        self.speak(
            f"Step completed. {step_label}.",
            key=f"completed_{step_label}",
        )

    def announce_skipped_step(self, expected_label: str) -> None:
        self.speak(
            f"Warning. The expected step was skipped. {expected_label}.",
            key="skipped",
        )

    def announce_out_of_sequence(self, expected_label: str) -> None:
        self.speak(
            f"Warning. Activity is out of sequence. Expected: {expected_label}.",
            key="out_of_sequence",
        )

    def announce_repeated_step(self, step_label: str) -> None:
        self.speak(
            f"Step repeated. {step_label}.",
            key="repeated",
        )

    def announce_uncertain(self) -> None:
        self.speak(
            "Unable to confidently identify the current activity.",
            key="uncertain",
        )

    def announce_experiment_completed(self) -> None:
        self.speak(
            "Experiment completed successfully.",
            key="experiment_completed",
        )

    def announce_experiment_paused(self) -> None:
        self.speak(
            "Experiment paused. Camera or detection unavailable.",
            key="experiment_paused",
        )

    # ------------------------------------------------------------------ ctrl

    def close(self) -> None:
        self._enabled = False
        self._engine = None

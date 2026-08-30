"""Camera manager: owns the capture thread, the latest frame, and the state
machine (DISCONNECTED / CONNECTED / ERROR).

The capture loop runs on a background daemon thread because OpenCV reads are
blocking; FastAPI only ever reads the latest frame / JPEG snapshot, so the
event loop is never blocked.

Locking rule: no method that acquires ``self._lock`` may call another
*locked* method while still holding it (``threading.Lock`` is not reentrant).
Shared state is snapshotted via ``_snapshot_locked`` when the lock is held and
via ``info()`` otherwise.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

from .capture import CameraError, CameraSettings, FrameReader, MockCamera, OpenCVCamera

logger = logging.getLogger("astraai.camera")

FRAME_BOUNDARY = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"


class CameraStatus(str, enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


class CameraManager:
    """Start/stop a camera, expose its latest frame, and serve MJPEG chunks."""

    def __init__(self, settings: Optional[CameraSettings] = None) -> None:
        self.settings = settings or CameraSettings()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._reader: Optional[FrameReader] = None
        self._status = CameraStatus.DISCONNECTED
        self._last_error: Optional[str] = None
        self._frame_id = 0
        self._context: tuple[int, np.ndarray, bytes] | None = None
        self._max_failures = 5

    # ------------------------------------------------------------------ state

    @property
    def status(self) -> CameraStatus:
        with self._lock:
            return self._status

    def is_running(self) -> bool:
        with self._lock:
            return self._running_locked()

    def _running_locked(self) -> bool:
        thread_alive = self._thread is not None and self._thread.is_alive()
        return thread_alive and self._status is CameraStatus.CONNECTED

    def info(self) -> dict:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict:
        """Status payload (camelCase keys, mirror-in-style). Lock must be held."""
        s = self.settings
        return {
            "status": self._status.value,
            "running": self._running_locked(),
            "source": self._reader.name if self._reader is not None else "none",
            "cameraIndex": s.camera_index,
            "width": s.width,
            "height": s.height,
            "fps": s.fps,
            "mock": s.mock,
            "frameCount": self._frame_id,
            "error": self._last_error,
        }

    # ------------------------------------------------------------------ frames

    def latest_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._context[1] if self._context is not None else None

    def latest_capture(self) -> tuple[int, np.ndarray] | None:
        """``(frame_id, last BGR frame)`` tuple, or ``None`` while idle.

        Side-car consumers (object detection) poll this to run only on new
        frames instead of the shared latest frame.
        """
        with self._lock:
            return (self._context[0], self._context[1]) if self._context is not None else None

    def latest_jpeg(self) -> tuple[int, bytes] | None:
        with self._lock:
            return (self._context[0], self._context[2]) if self._context is not None else None

    # ----------------------------------------------------------------- control

    def start(self) -> dict:
        """Open the camera and begin capturing. Idempotent when already
        running; returns the resulting status payload."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._snapshot_locked()
            self._release_locked()
            settings = self.settings
            reader = MockCamera(settings) if settings.mock else OpenCVCamera(settings)
            try:
                if not reader.open():
                    raise CameraError(
                        f"Could not open camera device {settings.camera_index}. "
                        "Check it is plugged in and not already in use."
                    )
            except CameraError as exc:
                logger.warning("Camera start failed: %s", exc)
                self._status = CameraStatus.ERROR
                self._last_error = str(exc)
                self._reader = reader
                return self._snapshot_locked()

            self._reader = reader
            self._status = CameraStatus.DISCONNECTED  # CONNECTED once a frame lands
            self._last_error = None
            self._frame_id = 0
            self._context = None
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="astraai-camera-capture",
                daemon=True,
            )
            self._thread.start()
            snapshot = self._snapshot_locked()
        logger.info(
            "Camera started (%s, index=%d, %dx%d @ %dfps)",
            reader.name,
            settings.camera_index,
            settings.width,
            settings.height,
            settings.fps,
        )
        return snapshot

    def stop(self) -> dict:
        """Stop capturing and release the device. Idempotent."""
        with self._lock:
            self._stop.set()
            thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        with self._lock:
            self._release_locked()
            self._status = CameraStatus.DISCONNECTED
            self._context = None
        logger.info("Camera stopped")
        return self.info()

    def close(self) -> None:
        """Best-effort stop used at server shutdown."""
        self.stop()

    def _release_locked(self) -> None:
        """Must be called while holding ``self._lock``."""
        self._stop.set()
        if self._reader is not None:
            try:
                self._reader.release()
            except Exception:  # noqa: BLE001 - release must never raise
                logger.exception("Camera release error")
            self._reader = None

    # ------------------------------------------------------------- capture loop

    def _capture_loop(self) -> None:
        failures = 0
        frame_interval = 1.0 / self.settings.fps if self.settings.fps > 0 else 0.0
        last_emit = 0.0
        reader = self._reader
        while not self._stop.is_set():
            try:
                frame = reader.read()
            except Exception as exc:  # noqa: BLE001 - keep the loop resilient
                logger.exception("Camera read error")
                self._set_error(f"Camera read error: {exc}")
                return
            if frame is None:
                failures += 1
                if failures >= self._max_failures:
                    self._set_error("Camera feed interrupted (device lost frames).")
                    return
                time.sleep(0.05)
                continue
            failures = 0
            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpeg_quality],
            )
            if not ok:
                self._set_error("Failed to encode camera frame as JPEG.")
                return
            with self._lock:
                self._frame_id += 1
                self._context = (self._frame_id, frame, encoded.tobytes())
                self._status = CameraStatus.CONNECTED
            if frame_interval > 0:
                elapsed = time.monotonic() - last_emit
                remaining = frame_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
                last_emit = time.monotonic()

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._status = CameraStatus.ERROR
            self._last_error = message
        logger.error("Camera ERROR: %s", message)

    # -------------------------------------------------------------- MJPEG feed

    async def mjpeg_frames(self):
        """Async generator yielding ``multipart/x-mixed-replace`` chunks.

        Reads the latest encoded frame from the capture thread; never blocks
        the event loop (tiny sleeps), and stops when the camera stops or the
        client disconnects.
        """
        last_id = -1
        sent_any = False
        while self.is_running():
            current = self.latest_jpeg()
            if current is not None and current[0] != last_id:
                last_id = current[0]
                sent_any = True
                yield FRAME_BOUNDARY + current[1] + b"\r\n"
            else:
                await asyncio.sleep(0.02)
        if sent_any:
            # One last frame flushes buffered stream content gracefully.
            current = self.latest_jpeg()
            if current is not None:
                yield FRAME_BOUNDARY + current[1] + b"\r\n"

    __call__ = mjpeg_frames
"""Camera capture layer: frame readers for a real webcam (OpenCV) and a
synthetic mock camera, plus the configurable settings shared with the manager.

Everything here stays local — no network, no cloud services.

Real-webcam robustness (backend fallback + frame validation):

- Windows Media Foundation can enumerate a device yet fail every grab
  (``MF_E_INVALIDREQUEST``) while DirectShow serves pixels or vice versa. The
  reader therefore probes candidate backends in order and adopts the FIRST one
  that actually returns a *valid* frame — never the first one that merely
  ``open()``s.
- A feed of black frames is rejected as invalid. The manager therefore never
  reports a camera CONNECTED and never hands pixels to the detector unless a
  real (non-blank) frame has been read.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np


class CameraError(Exception):
    """Raised when a camera device cannot be opened or misbehaves."""


@dataclass(frozen=True)
class CameraSettings:
    camera_index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    mock: bool = False
    jpeg_quality: int = 70
    #: Capture backend: ``auto`` probes (msmf, dshow, any) in order; a concrete
    #: value (``msmf`` | ``dshow`` | ``any``) tries only that one first.
    backend: str = "auto"
    #: Treat all-zero (black) frames as invalid so a dead sensor can never be
    #: mistaken for a live feed.
    reject_black: bool = True
    #: How many probe reads a backend gets before it is skipped.
    warmup_frames: int = 5


#: Candidate backends in preference order for ``auto``.
AUTO_BACKENDS: tuple[str, ...] = ("msmf", "dshow", "any")


def cv_backend(name: str) -> Optional[int]:
    """Map a backend name to an OpenCV ``CAP_*`` constant (None = default API)."""
    if name == "any":
        return getattr(cv2, "CAP_ANY", 0)
    return getattr(cv2, f"CAP_{name.upper()}", None)


def validate_frame(
    frame: Optional[np.ndarray],
    *,
    reject_black: bool = True,
) -> tuple[bool, str]:
    """``(valid, reason)`` — a frame only counts once it carries real pixels.

    The black test uses mean < 1 AND std < 1, so a genuinely dark scene (some
    legitimate pixel variance) still validates; a dead sensor's constant zeros
    do not.
    """
    if frame is None:
        return False, "no frame returned"
    if getattr(frame, "ndim", 0) != 3 or frame.dtype != np.uint8:
        return False, f"unexpected frame layout (shape={frame.shape!r}, dtype={frame.dtype!r})"
    height, width = frame.shape[:2]
    if height <= 0 or width <= 0:
        return False, "zero-size frame"
    if not reject_black:
        return True, "ok"
    if float(frame.mean()) < 1.0 and float(frame.std()) < 1.0:
        return False, "blank/black frame (no pixel content)"
    return True, "ok"


@dataclass
class ProbeAttempt:
    """One backend's open + warm-up result during ``select_backend``."""

    backend: str
    opened: bool
    reads_ok: int
    reads_failed: int
    valid_frame: bool
    error: str = ""

    @property
    def label(self) -> str:
        if not self.opened:
            return f"{self.backend}: not opened"
        return (
            f"{self.backend}: opened, warm-up {self.reads_ok}ok/{self.reads_failed}failed, "
            f"valid={'yes' if self.valid_frame else 'no'}"
        )


def select_backend(
    candidates: tuple[str, ...],
    open_fn: Callable[[str], object],
    read_fn: Callable[[object], Optional[np.ndarray]],
    release_fn: Callable[[object], None],
    *,
    reject_black: bool = True,
    max_warmup: int = 5,
) -> tuple[Optional[str], Optional[object], list[ProbeAttempt]]:
    """Probe candidates in order; adopt the first that yields a VALID frame.

    Returns ``(chosen_name, handle, attempts)``. When no candidate produces a
    valid frame, returns ``(None, None, attempts)`` with every attempt recorded
    for diagnostics — the caller decides how to surface that honestly.
    """
    attempts: list[ProbeAttempt] = []
    for name in candidates:
        cap: object | None = None
        try:
            cap = open_fn(name)
        except Exception as exc:  # noqa: BLE001 - recorded as a probe failure
            attempts.append(ProbeAttempt(name, False, 0, 0, False, error=str(exc)))
            continue
        if cap is None:
            attempts.append(ProbeAttempt(name, False, 0, 0, False))
            continue
        ok = failed = 0
        valid = False
        for _ in range(max(1, int(max_warmup))):
            try:
                frame = read_fn(cap)
            except Exception as exc:  # noqa: BLE001 - recorded per-backend
                failed += 1
                continue
            if frame is None:
                failed += 1
                continue
            ok += 1
            good, _ = validate_frame(frame, reject_black=reject_black)
            if good:
                valid = True
                break
        attempts.append(ProbeAttempt(name, True, ok, failed, valid))
        if valid:
            return name, cap, attempts
        try:
            release_fn(cap)
        except Exception:  # noqa: BLE001 - best effort
            pass
    return None, None, attempts


class FrameReader(ABC):
    """Contract every camera source satisfies (real or mock)."""

    @abstractmethod
    def open(self) -> bool:
        """Acquire the device. Returns False when unavailable."""

    @abstractmethod
    def read(self) -> Optional[np.ndarray]:
        """Block until the next frame. Returns None when the feed fails."""

    @abstractmethod
    def release(self) -> None:
        """Free the device. Idempotent."""


class OpenCVCamera(FrameReader):
    """Live webcam capture via ``cv2.VideoCapture`` with backend fallback.

    ``open()`` probes the candidate backends (see ``CameraSettings.backend``)
    and adopts the first that hands back a VALID warmed-up frame. A device that
    opens but streams black / none is reported with the full probe matrix
    instead of being silently presented as a working camera.
    """

    name = "webcam"

    def __init__(self, settings: CameraSettings) -> None:
        self.settings = settings
        self._capture: Optional[cv2.VideoCapture] = None
        self.backend: Optional[str] = None
        self.diagnostics: dict = {"probes": [], "warmup": 0}
        self._stats = {"reads": 0, "ok": 0, "failed": 0}
        self._last_error: Optional[str] = None

    # ----------------------------------------------------------- backend probe

    def _candidates(self) -> tuple[str, ...]:
        requested = (self.settings.backend or "auto").strip().lower()
        if requested == "auto":
            return AUTO_BACKENDS
        if requested == "mock":
            return AUTO_BACKENDS
        if requested in AUTO_BACKENDS:
            return (requested,)
        return AUTO_BACKENDS  # unknown value -> safe auto order

    def _open_handle(self, name: str) -> Optional[cv2.VideoCapture]:
        backend = cv_backend(name)
        if backend is None:
            return None
        capture = cv2.VideoCapture(self.settings.camera_index, backend)
        if not capture.isOpened():
            capture.release()
            return None
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.settings.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.settings.height)
        if self.settings.fps > 0:
            capture.set(cv2.CAP_PROP_FPS, self.settings.fps)
        return capture

    def _probe_read(self, capture: cv2.VideoCapture) -> Optional[np.ndarray]:
        try:
            ok, frame = capture.read()
        except cv2.error as exc:  # e.g. MF_E_INVALIDREQUEST surfaced by cv2
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None
        return frame if ok else None

    def open(self) -> bool:
        chosen, handle, attempts = select_backend(
            self._candidates(),
            open_fn=self._open_handle,
            read_fn=self._probe_read,
            release_fn=lambda cap: cap.release(),
            reject_black=self.settings.reject_black,
            max_warmup=self.settings.warmup_frames,
        )
        self.diagnostics = {
            "probes": [attempt.label for attempt in attempts],
            "warmup": self.settings.warmup_frames,
        }
        if chosen is None or handle is None:
            summary = "; ".join(attempt.label for attempt in attempts) or "no candidates"
            raise CameraError(
                f"Camera device {self.settings.camera_index} opened no usable feed "
                f"(probed: {summary}). Check it is not in use by another app and "
                "that its driver serves actual frames."
            )
        self._capture = handle
        self.backend = chosen
        self._last_error = None
        return True

    # ------------------------------------------------------------ frame reader

    def read(self) -> Optional[np.ndarray]:
        if self._capture is None:
            return None
        self._stats["reads"] += 1
        try:
            ok, frame = self._capture.read()
        except cv2.error as exc:
            self._stats["failed"] += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None
        if not ok or frame is None:
            self._stats["failed"] += 1
            self._last_error = "read returned no frame"
            return None
        self._stats["ok"] += 1
        self._last_error = None
        return frame

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self.backend = None


class MockCamera(FrameReader):
    """Synthetic frames so development and tests never need a webcam.

    Renders a moving target box plus a running frame counter — visually
    distinct from a live feed. ``open_ok=False`` simulates a camera that
    cannot be opened (the manager reports CAMERA ERROR).
    """

    name = "mock"

    def __init__(self, settings: CameraSettings, open_ok: bool = True, fail_after: Optional[int] = None) -> None:
        self.settings = settings
        self._open_ok = open_ok
        self._fail_after = fail_after
        self._count = 0
        self.backend = "mock"
        self.diagnostics: dict = {}

    def open(self) -> bool:
        if not self._open_ok:
            return False
        self._count = 0
        return True

    def read(self) -> Optional[np.ndarray]:
        if self._fail_after is not None and self._count >= self._fail_after:
            return None
        self._count += 1
        w, h = self.settings.width, self.settings.height
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (18, 24, 34)  # slate background
        step = self._count
        cx = (step * 6) % max(w - 160, 1)
        cy = h // 2 + int(np.sin(step / 6.0) * h * 0.25)
        cv2.rectangle(frame, (cx, cy), (cx + 120, cy + 80), (68, 90, 220), -1)
        cv2.rectangle(frame, (cx + 24, cy + 16), (cx + 96, cy + 64), (30, 60, 200), -1)
        label = f"MOCK CAMERA {step:04d}"
        cv2.putText(frame, label, (w // 2 - 140, h // 2 - 120), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (210, 210, 215), 2)
        cv2.putText(frame, f"{w}x{h}", (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 160, 180), 1)
        return frame

    def release(self) -> None:
        pass
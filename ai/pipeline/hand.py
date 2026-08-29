"""Hand landmark types and hand-tracking sources.

Standard 21-keypoint MediaPipe layout (wrist = index 0, fingertips =
4/8/12/16/20). ``BaseHandTracker`` is the seam: ``MockHandTracker`` runs
anywhere; ``MediaPipeHandTracker`` wraps MediaPipe Tasks (local, offline) and
is activated lazily — tests never require it.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import hypot
from pathlib import Path
from typing import Optional

import numpy as np

from .detections import Box

#: Standard MediaPipe hand-landmark indices.
WRIST_INDEX = 0
FINGER_TIPS = (4, 8, 12, 16, 20)
HAND_JOINTS = 21


@dataclass(frozen=True)
class HandLandmark:
    x: float  # normalized [0, 1] relative to the frame width
    y: float  # normalized [0, 1] relative to the frame height
    visibility: float = 1.0


@dataclass(frozen=True)
class HandLandmarkSet:
    """One detected hand with landmark positions in normalized units."""

    landmarks: tuple[HandLandmark, ...]  # exactly HAND_JOINTS entries
    handedness: str = "unknown"  # "left" / "right" / "unknown"
    timestamp: int = 0
    box: Optional[Box] = None  # pixel-space envelope, if known


def fingertip_pixels(hand: HandLandmarkSet, frame_size: tuple[int, int]) -> list[tuple[float, float]]:
    """Fingertip positions in pixels (used for hand→object distance)."""
    fw, fh = frame_size
    return [(hand.landmarks[i].x * fw, hand.landmarks[i].y * fh) for i in FINGER_TIPS]


def wrist_pixels(hand: HandLandmarkSet, frame_size: tuple[int, int]) -> tuple[float, float]:
    fw, fh = frame_size
    m = hand.landmarks[WRIST_INDEX]
    return (m.x * fw, m.y * fh)


def pixel_distance(hand: HandLandmarkSet, box: Box, frame_size: tuple[int, int]) -> float:
    """Shortest distance (px) from any fingertip to the box centre."""
    cx, cy = box.cx, box.cy
    best = float("inf")
    for fx, fy in fingertip_pixels(hand, frame_size):
        best = min(best, hypot(fx - cx, fy - cy))
    return best


class BaseHandTracker(ABC):
    """Contract every hand tracker satisfies."""

    name: str = "base"
    requires_weights: bool = False

    @abstractmethod
    def track(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[HandLandmarkSet]:
        """Return the hands visible in one BGR frame (possibly empty)."""
        raise NotImplementedError

    def close(self) -> None:
        """Release model resources if any (default: no-op)."""


def resolve_pose_model_path(path: str) -> Path:
    """Resolve ``models/pose/<name>`` like the YOLO resolver does."""
    p = Path(path)
    if p.is_absolute():
        return p
    env_dir = os.environ.get("BAS_MODELS_DIR")
    if env_dir:
        cand = Path(env_dir) / p
        if cand.exists():
            return cand
    root = Path(__file__).resolve().parent.parent.parent  # repo root
    return root / "models" / "pose" / p


class MockHandTracker(BaseHandTracker):
    """Deterministic synthetic hand(s) so the interaction stack runs with no
    model and no meaningful camera content. Hovers one hand mid-frame and
    fingers pulse gently — enough for pipeline/integration demos."""

    name = "mock_hand"
    requires_weights = False

    def __init__(self, phase: float = 0.0) -> None:
        self._tick = 0
        self._phase = phase

    def track(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[HandLandmarkSet]:
        import math

        self._tick += 1
        t = self._tick
        ts = int(timestamp_ms if timestamp_ms is not None else 0)
        h, w = frame.shape[:2]

        cx = w * (0.42 + 0.05 * math.sin(t / 9.0 + self._phase))
        cy = h * (0.62 + 0.04 * math.cos(t / 11.0))
        spread = 0.035 + 0.008 * math.sin(t / 3.0)
        palm = 0.05 + 0.004 * math.cos(t / 5.0)

        joints = [(0, 0), (-0.03, -0.08), (-0.05, -0.16), (-0.04, -0.24), (-0.02, -0.32)]  # thumb
        for finger_dx in (-0.05, 0.0, 0.05, 0.10):
            joints += [
                (finger_dx, -0.06),
                (finger_dx + spread, -0.14),
                (finger_dx + spread, -0.22),
                (finger_dx + spread, -0.30),
            ]
        assert len(joints) == 21  # noqa: S101
        landmarks = tuple(
            HandLandmark(
                x=max(0.0, min(1.0, (cx + dx * w) / w)),
                y=max(0.0, min(1.0, (cy + dy * h) / h)),
            )
            for dx, dy in joints
        )
        xs = [lm.x for lm in landmarks]
        ys = [lm.y for lm in landmarks]
        envelope = Box(
            x=int(min(xs) * w),
            y=int(min(ys) * h),
            width=int((max(xs) - min(xs)) * w),
            height=int((max(ys) - min(ys)) * h),
        )
        return [HandLandmarkSet(landmarks=landmarks, handedness="right", timestamp=ts, box=envelope)]

    def close(self) -> None:
        pass


class MediaPipeHandTracker(BaseHandTracker):
    """Real local hand landmarks via MediaPipe Tasks (mediapipe-tasks).

    Requires the package and a local ``hand_landmarker.task`` model in
    ``models/pose/``. Import and model load are lazy so the rest of the repo
    works (and tests run) without MediaPipe installed. MediaPipe runs fully
    offline; nothing is downloaded automatically.
    """

    name = "mediapipe"
    requires_weights = True

    def __init__(self, model_path: str = "hand_landmarker.task", num_hands: int = 2) -> None:
        self.model_path = model_path
        self.num_hands = num_hands
        self._landmarker: object = None  # mediapipe HandLandmarker

    def load(self) -> None:
        try:
            from mediapipe.tasks import python as mp_python  # noqa: F401
            from mediapipe.tasks.python import vision
        except ImportError as err:  # pragma: no cover - env dependent
            raise RuntimeError(
                "MediaPipe Tasks is not installed. `pip install mediapipe-tasks` "
                "into a supported Python (3.12/3.13 wheels; see docs)."
            ) from err
        from mediapipe.tasks.python.core.base_options import BaseOptions

        path = resolve_pose_model_path(self.model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Hand-landmark model not found: {path}. Drop hand_landmarker.task "
                f"into models/pose/ (see models/README.md)."
            )
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            num_hands=self.num_hands,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)  # type: ignore[attr-defined]

    def track(self, frame: np.ndarray, timestamp_ms: Optional[int] = None) -> list[HandLandmarkSet]:
        import mediapipe as mp  # pragma: no cover - env dependent

        if self._landmarker is None:
            self.load()
        ts = int(timestamp_ms if timestamp_ms is not None else 0)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
        result = self._landmarker.detect(mp_image)  # type: ignore[attr-defined]
        hands: list[HandLandmarkSet] = []
        h, w = frame.shape[:2]
        for i, hand_landmarks in enumerate(result.hand_landmarks):
            landmarks = tuple(
                HandLandmark(x=lm.x, y=lm.y, visibility=getattr(lm, "visibility", 1.0))
                for lm in hand_landmarks
            )
            xs = [lm.x for lm in landmarks]
            ys = [lm.y for lm in landmarks]
            handedness = "unknown"
            if result.handedness and i < len(result.handedness) and result.handedness[i]:
                handedness = result.handedness[i][0].category_name.lower()
            envelope = Box(
                x=int(min(xs) * w),
                y=int(min(ys) * h),
                width=int((max(xs) - min(xs)) * w),
                height=int((max(ys) - min(ys)) * h),
            )
            hands.append(HandLandmarkSet(landmarks=landmarks, handedness=handedness, timestamp=ts, box=envelope))
        return hands

    def close(self) -> None:
        if self._landmarker is not None:  # pragma: no cover - env dependent
            self._landmarker.close()
            self._landmarker = None
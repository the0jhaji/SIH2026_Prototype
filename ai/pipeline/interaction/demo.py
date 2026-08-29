"""Coherent mock scene: object detections + a hand, driven by a shared clock.

Drives a full, honest observation chain so the interaction module can be
demoed with no model and no camera:

    HAND_NEAR_YELLOW → YELLOW_MOVED → YELLOW_PLACED → HAND_NEAR_RED → RED_MOVED → RED_PLACED
"""

from __future__ import annotations

from ..detections import Box, ObjectDetection
from ..hand import HandLandmark, HandLandmarkSet

REFERENCE = (1280, 720)


def make_hand(cx: float, cy: float, handedness: str = "right") -> HandLandmarkSet:
    """21-keypoint hand whose fingertips sit near normalized (cx, cy). Only
    the fingertip positions matter for interaction tracking and tests."""
    joints: list[tuple[float, float]] = []
    for finger in range(5):
        joints += [(cx - 0.02, cy + 0.02), (cx, cy), (cx + finger * 0.002, cy), (cx, cy)]
    all_pts = [(cx - 0.03, cy - 0.04)] + joints
    landmarks = tuple(
        HandLandmark(x=max(0.0, min(1.0, x)), y=max(0.0, min(1.0, y))) for x, y in all_pts[:21]
    )
    return HandLandmarkSet(landmarks=landmarks, handedness=handedness)


class MockScene:
    """Deterministic tick-driven scene (all coordinates in REFERENCE units)."""

    def __init__(
        self,
        yellow_start: tuple[float, float] = (0.40, 0.50),
        red_start: tuple[float, float] = (0.16, 0.48),
        target: tuple[float, float] = (0.68, 0.80),
        box_size: tuple[float, float] = (0.09, 0.10),
        target_size: tuple[float, float] = (0.26, 0.15),
    ) -> None:
        self.yellow_start = yellow_start
        self.red_start = red_start
        self.target = target
        self.box_size = box_size
        self.target_size = target_size
        self._tick = 0

    def _square(self, center: tuple[float, float], size: tuple[float, float]) -> Box:
        w, h = REFERENCE
        cx, cy = center
        bw, bh = size
        return Box(
            x=max(0, int(cx * w - bw * w / 2)),
            y=max(0, int(cy * h - bh * h / 2)),
            width=max(1, int(bw * w)),
            height=max(1, int(bh * h)),
        )

    def _obj(self, class_name: str, center: tuple[float, float], size: tuple[float, float]) -> ObjectDetection:
        return ObjectDetection(
            class_name=class_name,
            confidence=0.9,
            bounding_box=self._square(center, size),
            timestamp=self._tick,
        )

    @staticmethod
    def _lerp(a: tuple[float, float], b: tuple[float, float], k: float) -> tuple[float, float]:
        return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)

    def _scene_at(self, t: int) -> tuple[list[ObjectDetection], list[HandLandmarkSet]]:
        yellow = self.yellow_start
        red = self.red_start
        if 16 <= t < 24:
            yellow = self._lerp(self.yellow_start, self.target, (t - 16) / 8.0)
        elif t >= 24:
            yellow = self.target
        if 64 <= t < 72:
            red = self._lerp(self.red_start, self.target, (t - 64) / 8.0)
        elif t >= 72:
            red = self.target

        if t <= 16:
            hand = self.yellow_start
        elif t < 24:
            hand = yellow
        elif t < 40:
            hand = self.target
        elif t < 48:
            hand = self._lerp(self.target, self.red_start, (t - 40) / 8.0)
        elif t < 64:
            hand = self.red_start
        elif t < 72:
            hand = red
        elif t < 88:
            hand = self.target
        else:
            hand = (0.08, 0.08)

        detections = [
            self._obj("person", (0.5, 0.15), (0.12, 0.35)),
            self._obj("red_box", red, self.box_size),
            self._obj("yellow_box", yellow, self.box_size),
            self._obj("target_area", self.target, self.target_size),
        ]
        return detections, [make_hand(*hand)]

    def step(self, frame_size: tuple[int, int]) -> tuple[list[ObjectDetection], list[HandLandmarkSet]]:
        """Advance one tick (first call → tick 1). Scene is authored in
        REFERENCE pixels; coordinates are re-projected onto ``frame_size``."""
        self._tick += 1
        detections, hands = self._scene_at(self._tick)
        fw, fh = frame_size
        sx, sy = fw / REFERENCE[0], fh / REFERENCE[1]
        rescaled = [
            ObjectDetection(
                class_name=d.class_name,
                confidence=d.confidence,
                bounding_box=Box(
                    x=int(d.bounding_box.x * sx),
                    y=int(d.bounding_box.y * sy),
                    width=max(1, int(d.bounding_box.width * sx)),
                    height=max(1, int(d.bounding_box.height * sy)),
                ),
                timestamp=d.timestamp,
            )
            for d in detections
        ]
        return rescaled, hands
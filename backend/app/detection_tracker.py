"""Temporal smoothing for the live detection feed (raw -> stable).

Promotes a raw single-frame detection to a *stable* detection only after the
same class+box has been seen for ``debounce_frames`` consecutive frames, and
smooths the emitted confidence and box with an EMA. This stops one-frame
classification flip-flops (pen -> bottle -> unknown) from reaching consumers
(prediction, safety, dashboard) without ever inventing detections — a stable
detection always corresponds to observations that actually happened.

Disappearance is immediate: an object that is no longer detected is not in the
stable output that frame, so absence / astronaut-down signals are never delayed.
A short grace window keeps the track alive so a one-frame flicker does not push
a confirmed object back through the whole debounce again.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Make the repo root importable so `ai.detection.types` resolves from the
# backend venv (same bootstrap as detection_service).
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai.detection.types import Detection

_IOU_THRESHOLD = 0.3
_GRACE_FRAMES = 1


@dataclass
class _Track:
    """One candidate object observed across frames (matched by class + box)."""

    class_name: str
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float
    seen: int = 0
    confirmed: bool = False
    last_matched: int = -1
    timestamp: int = 0
    instance_id: str | None = None


class TemporalTracker:
    """Debounces + EMA-smooths a stream of per-frame detections.

    ``unknown_object`` tracks carry a stable per-instance id so downstream
    consumers (attendance state machine) can follow one physical object across
    frames even though every generic proposal shares the same ``class_name``.
    """

    def __init__(
        self,
        debounce_frames: int = 2,
        alpha_conf: float = 0.35,
        alpha_box: float = 0.35,
    ) -> None:
        self.debounce_frames = max(1, int(debounce_frames or 1))
        self._a_conf = alpha_conf
        self._a_box = alpha_box
        self._tracks: list[_Track] = []
        self._seq = 0
        self._frame = 0

    # ------------------------------------------------------------- internals

    @staticmethod
    def _iou(t: _Track, d: Detection) -> float:
        a = (t.x1, t.y1, t.x2, t.y2)
        b = (float(d.x1), float(d.y1), float(d.x2), float(d.y2))
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        if inter <= 0.0:
            return 0.0
        uni = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / uni if uni > 0.0 else 0.0

    def _match(self, d: Detection) -> _Track | None:
        best: _Track | None = None
        best_iou = 0.0
        d_cx, d_cy = (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0
        for t in self._tracks:
            if t.class_name != d.class_name:
                continue
            iou = self._iou(t, d)
            contained = (t.x1 <= d_cx <= t.x2 and t.y1 <= d_cy <= t.y2) or (
                d.x1 <= (t.x1 + t.x2) / 2.0 <= d.x2 and d.y1 <= (t.y1 + t.y2) / 2.0 <= d.y2
            )
            score = iou if iou >= _IOU_THRESHOLD else (1.0 if contained else 0.0)
            if score > best_iou:
                best, best_iou = t, score
        return best

    # ------------------------------------------------------------------ api

    def update(self, detections: list[Detection]) -> list[Detection]:
        """Ingest one frame worth of raw detections; return the stable subset."""
        self._frame += 1
        matched: set[int] = set()
        out: list[Detection] = []
        for d in detections:
            t = self._match(d)
            if t is None:
                self._seq += 1
                t = _Track(
                    d.class_name,
                    d.confidence,
                    float(d.x1),
                    float(d.y1),
                    float(d.x2),
                    float(d.y2),
                    instance_id=f"unknown-{self._seq}" if d.class_name == "unknown_object" else None,
                )
                self._tracks.append(t)
            t.conf = self._a_conf * d.confidence + (1.0 - self._a_conf) * t.conf
            t.x1 = self._a_box * d.x1 + (1.0 - self._a_box) * t.x1
            t.y1 = self._a_box * d.y1 + (1.0 - self._a_box) * t.y1
            t.x2 = self._a_box * d.x2 + (1.0 - self._a_box) * t.x2
            t.y2 = self._a_box * d.y2 + (1.0 - self._a_box) * t.y2
            t.seen += 1
            t.timestamp = d.timestamp
            t.last_matched = self._frame
            if t.seen >= self.debounce_frames:
                t.confirmed = True
            matched.add(id(t))
        self._tracks = [
            t for t in self._tracks
            if id(t) in matched or self._frame - t.last_matched <= _GRACE_FRAMES
        ]
        for t in self._tracks:
            if not (t.confirmed and id(t) in matched):
                continue
            out.append(
                Detection(
                    class_name=t.class_name,
                    confidence=round(t.conf, 4),
                    x1=max(0, int(round(t.x1))),
                    y1=max(0, int(round(t.y1))),
                    x2=max(0, int(round(t.x2))),
                    y2=max(0, int(round(t.y2))),
                    timestamp=t.timestamp,
                    instance_id=t.instance_id,
                )
            )
        out.sort(key=lambda d: -d.confidence)
        return out

    @property
    def pending(self) -> int:
        """Raw candidates not yet promoted (debugging only)."""
        return sum(1 for t in self._tracks if not t.confirmed)
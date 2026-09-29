"""Temporal hand⇄object interaction tracking.

Produces HAND_NEAR_*/MOVED/PLACED observations from per-frame object
detections and hand landmarks. It is entirely independent of the experiment
state machine — these are low-level, honest observations:

- HAND_NEAR_*  — a hand is spatially near an object (proximity only).
- *_MOVED      — the object stayed displaced for N consecutive frames
                  (temporal motion, not proximity).
- *_PLACED      — after a confirmed move episode, the object settled at rest
                  inside the target area.

Proximity alone never fires MOVED or PLACED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from typing import Optional

from ..detections import Box, ObjectDetection
from ..hand import HandLandmarkSet, pixel_distance, wrist_pixels
from . import geometry
from .events import OBJECT_TO_PREFIX, InteractionEvent, InteractionEventType


@dataclass(frozen=True)
class InteractionConfig:
    near_mult: float = 0.90  # hand→object near if distance ≤ near_mult × object diagonal
    move_mult: float = 0.30  # per-frame displacement (× object diagonal) counts as moving
    min_move_frames: int = 2  # consecutive moving frames before *_MOVED fires
    settle_mult: float = 0.10  # per-frame displacement at/below this counts as at rest
    settle_frames: int = 3  # consecutive rest frames before *_PLACED can fire
    idle_frames: int = 30  # drop object tracks unseen for this many frames
    target_margin: float = 0.15  # proportional margin around the target_area box
    max_assoc_distance: float = 0.25  # fraction of the frame diagonal for object continuity
    hand_assoc_distance: float = 0.25  # normalized wrist distance for hand continuity
    #: Optional class_name → event-prefix map for objects beyond the built-in
    #: demo pair (e.g. {"experiment_box": "EXPERIMENT"}). When set it also
    #: defines which classes the tracker reasons about.
    class_prefixes: Optional[dict[str, str]] = None


@dataclass
class ObjectTrack:
    class_name: str
    instance: int
    bbox: Box
    center: tuple[float, float]
    last_ts: int
    prev_center: Optional[tuple[float, float]] = None
    gap_frames: int = 0
    moving_frames: int = 0
    stable_frames: int = 0
    moved: bool = False
    held: bool = False
    near_hand_ids: tuple[int, ...] = field(default_factory=tuple)
    last_displacement: float = 0.0

    @property
    def key(self) -> tuple[str, int]:
        return (self.class_name, self.instance)


class InteractionTracker:
    """Stateful tracker. Call :meth:`update` once per frame."""

    @property
    def supported_classes(self) -> tuple[str, ...]:
        """Object classes the tracker reasons about (→ PREFIX events). A custom
        ``class_prefixes`` map widens (or replaces) the built-in demo pair."""
        return (
            tuple(self.config.class_prefixes or ())
            or tuple(OBJECT_TO_PREFIX)
        )

    def __init__(self, config: Optional[InteractionConfig] = None) -> None:
        self.config = config or InteractionConfig()
        self.reset()

    def reset(self) -> None:
        self._tracks: list[ObjectTrack] = []
        self._hands: dict[int, HandLandmarkSet] = {}
        self._near_pairs: set[tuple[int, tuple[str, int]]] = set()
        self._hand_seq = 0
        self._target_area: Optional[Box] = None
        self._frame = 0

    @property
    def object_tracks(self) -> tuple[ObjectTrack, ...]:
        return tuple(self._tracks)

    # ------------------------------------------------------------------ utils

    def _name(self, class_name: str, kind: str) -> InteractionEventType:
        prefixes = self.config.class_prefixes or OBJECT_TO_PREFIX
        prefix = prefixes[class_name]
        name = f"HAND_NEAR_{prefix}" if kind == "NEAR" else f"{prefix}_{kind}"
        return name  # type: ignore[return-value]

    def _near_confidence(self, distance: float, track: ObjectTrack) -> float:
        diag = geometry.object_diagonal(track.bbox)
        max_near = self.config.near_mult * diag
        if max_near <= 0:
            return 0.5
        closeness = max(0.0, min(1.0, 1.0 - distance / max_near))
        return round(min(0.99, 0.55 + 0.44 * closeness), 3)

    def _move_confidence(self, track: ObjectTrack) -> float:
        base = 0.75 + 0.05 * min(track.moving_frames, 4)
        if track.held:
            base += 0.10
        return round(min(0.99, base), 2)

    # ---------------------------------------------------------------- update

    def update(
        self,
        detections: list[ObjectDetection],
        hands: list[HandLandmarkSet],
        frame_size: tuple[int, int],
        timestamp: int,
    ) -> list[InteractionEvent]:
        """Advance one frame and return the events observed this frame."""
        events: list[InteractionEvent] = []
        self._frame += 1
        fw, fh = frame_size
        frame_diag = hypot(fw, fh)

        self._target_area = next(
            (d.bounding_box for d in detections if d.class_name == "target_area"), None
        )

        self._associate_hands(hands, frame_size)
        self._associate_objects(detections, frame_diag, timestamp)

        for track in self._tracks:
            diag = geometry.object_diagonal(track.bbox) or 1.0
            near_ids = [
                hid
                for hid, hand in self._hands.items()
                if geometry.hand_proximity(hid, hand, track.bbox, frame_size, self.config.near_mult).near
            ]
            track.near_hand_ids = tuple(near_ids)

            if track.prev_center is not None:
                displacement = hypot(
                    track.center[0] - track.prev_center[0],
                    track.center[1] - track.prev_center[1],
                )
                if track.gap_frames > 0:
                    displacement = 0.0  # jumps across detection gaps are not motion
                track.last_displacement = displacement
                if displacement > self.config.move_mult * diag:
                    track.moving_frames += 1
                    track.stable_frames = 0
                else:
                    track.moving_frames = 0
                    track.stable_frames += 1
            track.prev_center = track.center

            # MOVED: several consecutive frames of displacement.
            if (
                not track.moved
                and track.moving_frames >= self.config.min_move_frames
            ):
                track.moved = True
                track.held = bool(near_ids)
                events.append(
                    InteractionEvent(
                        name=self._name(track.class_name, "MOVED"),
                        object_class=track.class_name,
                        timestamp=timestamp,
                        confidence=self._move_confidence(track),
                        hand_id=(near_ids[0] if near_ids else None),
                        displacement=round(track.last_displacement, 1),
                    )
                )

            # PLACED: after a confirmed move, the object must come to rest
            # inside the target area for several consecutive frames.
            if track.moved and track.moving_frames == 0 and track.stable_frames >= self.config.settle_frames:
                placed = (
                    self._target_area is not None
                    and geometry.centre_inside_box(track.center, self._target_area, self.config.target_margin)
                )
                if placed:
                    events.append(
                        InteractionEvent(
                            name=self._name(track.class_name, "PLACED"),
                            object_class=track.class_name,
                            timestamp=timestamp,
                            confidence=0.9 if track.held else 0.82,
                            hand_id=(track.near_hand_ids[0] if track.near_hand_ids else None),
                            in_target_area=True,
                        )
                    )
                # Either way the episode ends: a motionless object proves nothing.
                track.moved = False
                track.stable_frames = 0
                track.held = False

        # HAND_NEAR on proximity transitions (enter only, debounced by the set).
        current_pairs = {
            (hid, track.key) for track in self._tracks for hid in track.near_hand_ids
        }
        for hid, key in current_pairs - self._near_pairs:
            track = next(t for t in self._tracks if t.key == key)
            hand = self._hands[hid]
            distance = pixel_distance(hand, track.bbox, frame_size)
            events.append(
                InteractionEvent(
                    name=self._name(track.class_name, "NEAR"),
                    object_class=track.class_name,
                    timestamp=timestamp,
                    confidence=self._near_confidence(distance, track),
                    hand_id=hid,
                    distance=round(distance, 1),
                )
            )
        self._near_pairs = current_pairs

        self._prune()
        return events

    # ------------------------------------------------------------- internals

    def _associate_hands(self, hands: list[HandLandmarkSet], frame_size: tuple[int, int]) -> None:
        frame_diag = hypot(frame_size[0], frame_size[1]) or 1.0
        used: set[int] = set()
        assigned: dict[int, HandLandmarkSet] = {}
        for hand in hands:
            best_id: Optional[int] = None
            best_dist = self.config.hand_assoc_distance
            hw = wrist_pixels(hand, frame_size)
            for hid, prev in self._hands.items():
                if hid in used:
                    continue
                pw = wrist_pixels(prev, frame_size)
                w_dist = hypot(hw[0] - pw[0], hw[1] - pw[1]) / frame_diag
                if w_dist < best_dist:
                    best_dist = w_dist
                    best_id = hid
            hid = best_id if best_id is not None else self._hand_seq
            if best_id is None:
                self._hand_seq += 1
            used.add(hid)
            assigned[hid] = hand
        self._hands = assigned

    def _associate_objects(
        self, detections: list[ObjectDetection], frame_diag: float, timestamp: int
    ) -> None:
        max_d = self.config.max_assoc_distance * frame_diag
        taken: set[tuple[str, int]] = set()
        remaining = []
        for det in detections:
            if det.class_name not in self.supported_classes:
                continue
            box = det.bounding_box
            center = (box.cx, box.cy)
            candidates = [
                t for t in self._tracks
                if t.class_name == det.class_name and t.key not in taken
            ]
            chosen = min(
                candidates,
                key=lambda t: hypot(t.center[0] - center[0], t.center[1] - center[1])
                if candidates
                else 0,
                default=None,
            )
            if chosen is not None:
                dist = hypot(chosen.center[0] - center[0], chosen.center[1] - center[1])
                if dist <= max_d:
                    chosen.bbox = box
                    chosen.center = center
                    chosen.last_ts = timestamp
                    chosen.gap_frames = 0
                    taken.add(chosen.key)
                    continue
            instance = 0
            used_instances = {t.instance for t in self._tracks if t.class_name == det.class_name}
            while instance in used_instances:
                instance += 1
            remaining.append(ObjectTrack(det.class_name, instance, box, center, timestamp))
        for track in self._tracks:
            if track.key not in taken:
                track.gap_frames += 1
        self._tracks = [t for t in self._tracks if t.gap_frames <= self.config.idle_frames]
        self._tracks.extend(remaining)

    def _prune(self) -> None:
        pass  # gaps already pruned in _associate_objects
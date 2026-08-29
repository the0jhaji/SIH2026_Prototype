"""Pure geometry helpers for hand↔object interaction (no state)."""

from __future__ import annotations

from dataclasses import dataclass

from ..detections import Box
from ..hand import HandLandmarkSet, pixel_distance


@dataclass(frozen=True)
class HandProximity:
    hand_id: int
    distance_px: float  # nearest fingertip → object centre
    near: bool


def object_diagonal(box: Box) -> float:
    return (box.width**2 + box.height**2) ** 0.5


def hand_proximity(
    hand_id: int,
    hand: HandLandmarkSet,
    box: Box,
    frame_size: tuple[int, int],
    near_mult: float,
) -> HandProximity:
    """Distance from a hand to an object and whether it is within the near
    envelope. Proximity is *observational* — it is never treated as proof of
    picking an object up."""
    distance = pixel_distance(hand, box, frame_size)
    diag = object_diagonal(box)
    threshold = near_mult * diag if diag > 0 else 0.0
    return HandProximity(hand_id=hand_id, distance_px=distance, near=distance <= threshold)


def centre_inside_box(centre: tuple[float, float], box: Box, margin_ratio: float = 0.0) -> bool:
    """True when a point is inside a box, optionally bloated by a margin
    proportional to the box diagonal."""
    diag = object_diagonal(box)
    margin = margin_ratio * diag
    return (
        box.x - margin <= centre[0] <= box.x + box.width + margin
        and box.y - margin <= centre[1] <= box.y + box.height + margin
    )
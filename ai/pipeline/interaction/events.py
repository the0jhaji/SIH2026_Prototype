"""Interaction events emitted by the interaction tracker.

Independent of the experiment state machine: these are low-level spatial /
temporal observations of hands and objects, not activity classifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

#: Default event vocabulary produced by the tracker for the built-in demo
#: classes (red_box/yellow_box). A custom prefix map (InteractionConfig.
#: class_prefixes) extends this to other experiment objects — the resulting
#: event names remain ``{PREFIX}_{KIND}`` / ``HAND_NEAR_{PREFIX}`` strings.
InteractionEventType = Literal[
    "HAND_NEAR_RED",
    "HAND_NEAR_YELLOW",
    "RED_MOVED",
    "YELLOW_MOVED",
    "RED_PLACED",
    "YELLOW_PLACED",
]

#: Abstract objects (class names) → broad event prefix.
OBJECT_TO_PREFIX: dict[str, str] = {
    "red_box": "RED",
    "yellow_box": "YELLOW",
}


@dataclass(frozen=True)
class InteractionEvent:
    """One observation. ``name`` is derived from the object class plus the
    observed state; messages never claim a pick/place action was intentful."""

    name: str
    object_class: str
    timestamp: int
    confidence: float
    hand_id: Optional[int] = None
    distance: Optional[float] = None
    displacement: Optional[float] = None
    in_target_area: Optional[bool] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "object": self.object_class,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "hand_id": self.hand_id,
            "distance_px": self.distance,
            "displacement_px": self.displacement,
            "in_target_area": self.in_target_area,
        }
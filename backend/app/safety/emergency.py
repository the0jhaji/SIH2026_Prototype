"""Astronaut injury / emergency candidate detection.

This module does NOT claim medical diagnosis. It produces *emergency
candidates* — temporal observations that MAY indicate an astronaut problem —
using only what a camera + detection feed can honestly support:

  * ASTRONAUT_DOWN / POSSIBLE_INJURY: an astronaut was visible for a while and
    then suddenly stops being detected, persisting for N frames.
  * NO_MOTION: the astronaut box stays (nearly) stationary for N frames.
  * POSSIBLE_COLLISION: a confirmed CRITICAL-level hazard sits right next to
    the astronaut.

Every candidate needs temporal confirmation before it becomes a confirmed
emergency. A real pose / HAR model plugs in at this same seam later (the
``signal_types`` are the contract); until then no pose-based claims are made.

Sources:
  * ``rules`` (default) — rule-based candidates from the detection feed.
  * ``sim`` — scripted signals (``EMERGENCY_BACKEND=sim``) for demos/tests.
  * ``none`` — never emit emergency candidates.
Explicit signals can also be injected (``inject()``) by tests or a future
pose/interaction module.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, List, Optional

from pydantic import BaseModel, ConfigDict

POSSIBLE_INJURY = "POSSIBLE_INJURY"
POSSIBLE_COLLISION = "POSSIBLE_COLLISION"
ASTRONAUT_DOWN = "ASTRONAUT_DOWN"
ASTRONAUT_UNOBSERVED = "ASTRONAUT_UNOBSERVED"
NO_MOTION = "NO_MOTION"
EMERGENCY_CANDIDATE = "EMERGENCY_CANDIDATE"

SIGNAL_TYPES = (
    POSSIBLE_INJURY,
    POSSIBLE_COLLISION,
    ASTRONAUT_DOWN,
    ASTRONAUT_UNOBSERVED,
    NO_MOTION,
    EMERGENCY_CANDIDATE,
)

MIN_ASTRONAUT_CONFIDENCE = 0.5


class EmergencySignal(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_type: str
    confirmed: bool
    confidence: float
    description: str
    recommended_action: str = ""
    timestamp: int = 0
    source: str = "rules"


class SimScriptItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    at_tick: int
    event_type: str
    confirmed: bool
    confidence: float
    description: str
    recommended_action: str = ""


class EmergencyManager:
    """Owns the astronaut-emergency temporal state machine."""

    def __init__(
        self,
        backend: str = "rules",
        *,
        absent_frames: int = 8,
        static_frames: int = 30,
        static_epsilon_px: float = 2.0,
        sim_script: Optional[List[SimScriptItem]] = None,
    ) -> None:
        self.backend = backend
        self.absent_frames = max(2, absent_frames)
        self.static_frames = max(2, static_frames)
        self.static_epsilon_px = static_epsilon_px
        self.sim_script = sim_script or []
        self._injected: Deque[EmergencySignal] = deque()
        self._tick = 0
        self._latest: Optional[EmergencySignal] = None
        self._present_frames = 0
        self._absent_frames = 0
        self._was_present = False
        self._static_frames = 0
        self._last_center: Optional[tuple[float, float]] = None

    def reset(self) -> None:
        self._injected.clear()
        self._tick = 0
        self._latest = None
        self._present_frames = 0
        self._absent_frames = 0
        self._was_present = False
        self._static_frames = 0
        self._last_center = None

    def inject(self, signal: EmergencySignal) -> None:
        """Inject an explicit emergency signal (tests / future pose module)."""
        self._injected.append(signal)

    def latest(self) -> Optional[EmergencySignal]:
        return self._latest

    # ----------------------------------------------------------------- logic

    def update(self, payload: Optional[dict], scene, now: Optional[int] = None) -> Optional[EmergencySignal]:
        """One assessment cycle. Returns the current (possibly None) signal."""
        now = now if now is not None else int(time.time() * 1000)
        self._tick += 1

        if self._injected:
            signal = self._injected.popleft()
            signal.timestamp = now
            self._latest = signal
            return signal

        if self.backend == "none":
            self._latest = None
            return None

        if self.backend == "sim":
            for item in self.sim_script:
                if item.at_tick == self._tick:
                    signal = EmergencySignal(
                        event_type=item.event_type,
                        confirmed=item.confirmed,
                        confidence=item.confidence,
                        description=item.description,
                        recommended_action=item.recommended_action,
                        timestamp=now,
                        source="sim",
                    )
                    self._latest = signal
                    return signal
            self._latest = None
            return None

        # backend == "rules"
        signal = self._rules_update(payload, scene, now)
        self._latest = signal
        return signal

    def _astronaut_box(self, payload: Optional[dict]) -> Optional[dict]:
        if not payload:
            return None
        for d in payload.get("detections") or []:
            if d.get("class_name") == "person" and float(d.get("confidence", 0)) >= MIN_ASTRONAUT_CONFIDENCE:
                return d
        return None

    def _rules_update(self, payload: Optional[dict], scene, now: int) -> Optional[EmergencySignal]:
        box = self._astronaut_box(payload)
        present = box is not None

        if present:
            self._was_present = True
            self._absent_frames = 0
            self._present_frames += 1
            center = ((box["x1"] + box["x2"]) / 2.0, (box["y1"] + box["y2"]) / 2.0)
            if self._last_center is not None:
                dx = center[0] - self._last_center[0]
                dy = center[1] - self._last_center[1]
                moved = (dx * dx + dy * dy) ** 0.5 > self.static_epsilon_px
                if moved:
                    self._static_frames = 0
                else:
                    self._static_frames += 1
            self._last_center = center
        else:
            self._static_frames = 0
            self._last_center = None
            # Once the astronaut was visible, keep counting absence (the
            # episode flag must survive the first absent tick).
            if self._was_present:
                self._absent_frames += 1

        # Collision candidate: confirmed CRITICAL hazard right next to astronaut.
        if present and scene is not None:
            for assessment in scene.hazards:
                if (
                    assessment.confirmed
                    and assessment.risk_level == "CRITICAL"
                    and assessment.near_astronaut
                ):
                    return EmergencySignal(
                        event_type=POSSIBLE_COLLISION,
                        confirmed=False,
                        confidence=assessment.confidence,
                        description=(
                            f"Confirmed {assessment.object} hazard at CRITICAL risk near the "
                            f"astronaut — possible collision."
                        ),
                        recommended_action=assessment.recommended_action,
                        timestamp=now,
                        source="rules",
                    )

        # Astronaut disappeared after being present.
        if self._was_present and not present and self._absent_frames >= self.absent_frames:
            confirmed = self._absent_frames >= 2 * self.absent_frames
            return EmergencySignal(
                event_type=ASTRONAUT_DOWN if confirmed else ASTRONAUT_UNOBSERVED,
                confirmed=confirmed,
                confidence=0.75,
                description=(
                    "Astronaut was detected and is no longer visible for "
                    f"{self._absent_frames} assessment frames — possible sudden collapse/fall."
                    if not confirmed
                    else "Astronaut still unobserved after prolonged absence — possible injury emergency."
                ),
                recommended_action="Confirm astronaut status; dispatch help",
                timestamp=now,
                source="rules",
            )

        # Prolonged immobility while visible.
        if present and self._present_frames >= 3 and self._static_frames >= self.static_frames:
            confirmed = self._static_frames >= 2 * self.static_frames
            return EmergencySignal(
                event_type=NO_MOTION if not confirmed else POSSIBLE_INJURY,
                confirmed=confirmed,
                confidence=0.7,
                description=(
                    f"Astronaut visually stationary for {self._static_frames} assessment frames "
                    "— prolonged immobility within a module task area."
                ),
                recommended_action="Confirm astronaut status; check distress cues",
                timestamp=now,
                source="rules",
            )

        return None

    def status(self) -> dict:
        return {
            "backend": self.backend,
            "tick": self._tick,
            "latestEventType": self._latest.event_type if self._latest else None,
            "latestConfirmed": self._latest.confirmed if self._latest else False,
            "presentFrames": self._present_frames,
            "absentFrames": self._absent_frames,
            "staticFrames": self._static_frames,
        }
"""Safety incident state machine.

Replaces the box-experiment concept with a *safety incident* lifecycle:

    NORMAL -> OBSERVING -> CAUTION -> WARNING -> CRITICAL -> EMERGENCY
        and, when the hazard clears:  -> RESOLVED -> NORMAL

States:
  NORMAL       no active risks / clean feed
  OBSERVING    one or more UNCONFIRMED hazard candidates (not yet temporal)
  CAUTION      confirmed low risk
  WARNING      confirmed moderate risk
  CRITICAL     confirmed high risk (near astronaut/equipment)
  EMERGENCY    confirmed astronaut emergency (possible injury / life threat)
  ACKNOWLEDGED operator acknowledged the active alert/incident
  RESOLVED     hazard cleared for N consecutive fresh frames (never on a dead feed)

The monitor ONLY classifies; it never creates incidents or alerts — the
SafetyService orchestrator does that from the emitted events.
"""

from __future__ import annotations

import time
from typing import List, Optional

from .. import config
from .hazard_engine import SceneAssessment

STATE_ORDER = ["NORMAL", "OBSERVING", "CAUTION", "WARNING", "CRITICAL", "EMERGENCY"]
Severity = str  # info | ok | warn | error


class SafetyMonitor:
    def __init__(
        self,
        *,
        resolve_cycles: int = 2,
    ) -> None:
        self.resolve_cycles = max(1, resolve_cycles)
        self.state = "NORMAL"
        self.acked_level = 0
        self.pending_ack = False
        self._clean_cycles = 0
        self._fired_confirmations: set[str] = set()
        self.active_since = 0.0
        self._last_ts = 0

    def reset(self) -> None:
        self.state = "NORMAL"
        self.acked_level = 0
        self.pending_ack = False
        self._clean_cycles = 0
        self._fired_confirmations.clear()

    # ------------------------------------------------------------------ events

    def _event(
        self,
        kind: str,
        message: str,
        severity: Severity = "info",
        level: Optional[str] = None,
        **extra: object,
    ) -> dict:
        return {
            "ts": self._last_ts,
            "kind": kind,
            "severity": severity,
            "message": message,
            "level": level,
            **extra,
        }

    def _index_of(self, state: str) -> int:
        if state in STATE_ORDER:
            return STATE_ORDER.index(state)
        if state == "ACKNOWLEDGED":
            return max(self.acked_level, 0)
        return 0  # RESOLVED / unknown

    def _transition(self, target: str, reason: str) -> List[dict]:
        if target == self.state:
            return []
        old = self.state
        self.state = target
        self.active_since = self._last_ts
        return [
            self._event(
                "SAFETY_STATE_CHANGED",
                f"Safety monitor {old} -> {target}: {reason}",
                severity="warn" if self._index_of(target) >= STATE_ORDER.index("WARNING") else "info",
                level=target,
                from_state=old,
                to_state=target,
            )
        ]

    # ------------------------------------------------------------------ update

    def start(self, now: Optional[int] = None) -> List[dict]:
        self._last_ts = now if now is not None else int(time.time() * 1000)
        return [self._event("SAFETY_MONITOR_STARTED", "Safety monitoring started", severity="ok")]

    def stop(self, now: Optional[int] = None) -> List[dict]:
        self._last_ts = now if now is not None else int(time.time() * 1000)
        self._fired_confirmations.clear()
        return [self._event("SAFETY_MONITOR_STOPPED", "Safety monitoring stopped", severity="info")]

    def emergency_target(self, emergency, scene: SceneAssessment) -> str:
        """The mission state the scene calls for. Confirmed emergencies always
        dominate; unconfirmed emergency candidates warrant at least WARNING;
        otherwise the hazard assessment itself drives the level."""
        if emergency is not None and emergency.confirmed:
            return "EMERGENCY"
        hazard_index = self._hazard_index(scene) if scene is not None else 0
        if emergency is not None:
            hazard_index = max(hazard_index, STATE_ORDER.index("WARNING"))
        return STATE_ORDER[hazard_index]

    @staticmethod
    def _hazard_index(scene: SceneAssessment) -> int:
        if scene.has_active_hazards:
            level = scene.overall_risk_level
            for s in ("CRITICAL", "WARNING", "CAUTION"):
                if level == s:
                    return STATE_ORDER.index(s)
        if scene.has_candidates:
            return STATE_ORDER.index("OBSERVING")
        return STATE_ORDER.index("NORMAL")

    def update(
        self,
        scene: SceneAssessment,
        emergency,
        now: Optional[int] = None,
    ) -> List[dict]:
        """One assessment cycle -> monitor events (state changes, new
        confirmations). A stale scene produces NO transitions: a dead camera
        feed must never auto-resolve or auto-escalate a hazard."""
        now = now if now is not None else int(time.time() * 1000)
        self._last_ts = now
        events: List[dict] = []

        if scene.stale:
            return events

        target = self.emergency_target(emergency, scene)
        target_index = STATE_ORDER.index(target)
        current_index = self._index_of(self.state)

        # Confirmation events for freshly confirmed hazards.
        for a in scene.hazards:
            uid = f"{a.object}:{a.hazard_type or ''}"
            if a.confirmed and uid not in self._fired_confirmations:
                self._fired_confirmations.add(uid)
                events.append(
                    self._event(
                        "HAZARD_CONFIRMED",
                        f"Confirmed hazard: {a.object} ({a.hazard_type or 'unknown type'}) "
                        f"risk {a.risk_level} {a.risk_score:.0%}",
                        severity="warn",
                        level=a.risk_level,
                        object=a.object,
                        risk_score=a.risk_score,
                    )
                )

        # Candidate-only (first sighting) events.
        if target_index >= STATE_ORDER.index("OBSERVING") and current_index < STATE_ORDER.index("OBSERVING") and target == "OBSERVING":
            events.append(self._event("HAZARD_CANDIDATE", "Hazard candidate observed — confirming over frames", severity="info", level="OBSERVING"))

        if target_index <= current_index:
            # Same or lower risk: accumulate clean cycles for resolution.
            if target_index == 0 and current_index > 0:
                self._clean_cycles += 1
                if self._clean_cycles >= self.resolve_cycles:
                    self._clean_cycles = 0
                    events.extend(self._transition("RESOLVED", "confirmed hazards cleared"))
                    return events
                return events
            # Acknowledged state: survive lower risks, escalate on higher ones.
            if self.state == "ACKNOWLEDGED":
                if target_index > self.acked_level:
                    events.extend(self._transition(target, "risk escalated above acknowledged level"))
                return events
            if self.state == "RESOLVED":
                if target_index == 0:
                    events.extend(self._transition("NORMAL", "environment clear"))
                else:
                    events.extend(self._transition(target, "new risk after resolution"))
                return events
            # Stay (equal or slightly lower) — do not auto de-escalate.
            if target_index == current_index:
                return events
            if target_index < current_index:
                self._clean_cycles = 0
                return events

        # Escalation path.
        self._clean_cycles = 0
        events.extend(self._transition(target, f"risk escalated to {target}"))

        # Confirmed emergency is always its own distinct event.
        if emergency is not None and emergency.confirmed:
            events.append(
                self._event(
                    "EMERGENCY_DETECTED",
                    f"CONFIRMED emergency candidate: {emergency.event_type} — {emergency.description}",
                    severity="error",
                    level="EMERGENCY",
                    event_type=emergency.event_type,
                    confidence=emergency.confidence,
                )
            )
        return events

    def acknowledge(self, note: str = "", now: Optional[int] = None) -> List[dict]:
        now = now if now is not None else int(time.time() * 1000)
        self._last_ts = now
        self.acked_level = STATE_ORDER.index(self.state) if self.state != "NORMAL" else 0
        self.pending_ack = False
        events = self._transition("ACKNOWLEDGED", "operator acknowledged the active risk")
        return events + [
            self._event(
                "ALERT_ACKNOWLEDGED",
                f"Operator acknowledged the active risk" + (f": {note}" if note else ""),
                severity="info",
                level=self.state,
                note=note,
            )
        ]

    def snapshot(self) -> dict:
        if self.state in STATE_ORDER:
            index = STATE_ORDER.index(self.state)
        elif self.state == "ACKNOWLEDGED":
            index = max(self.acked_level, 0)
        else:  # RESOLVED
            index = 0
        return {
            "state": self.state,
            "stateIndex": index,
            "activeSince": int(self.active_since) if self.active_since else None,
            "ackedLevel": self.acked_level,
        }
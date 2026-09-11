"""AttendanceMonitor: held vs unattended state machine for unknown objects.

Consumes the *unknown-object* feed (``DetectionService.latest()``) together
with the known ``person`` detections, and answers one question per unknown
object: was it held, and once it left the hand, did it stay unattended long
enough to warn about?

The state machine per tracked object:

    UNKNOWN_DETECTED -> POSSIBLY_HELD -> HELD -> RELEASED -> UNATTENDED

- A proposal only becomes POSSIBLY_HELD when it sits inside the person's
  *arm-reach* region (head/upper-torso band plus a configurable margin out to
  each side) — never merely any overlap with the person's bounding box, so a
  hammer drifting past the astronaut's leg is not called "held".
- HELD requires ``held_frames`` consecutive near-person observations.
- RELEASED happens the first frame the object leaves the reach region.
- UNATTENDED (the alert trigger) requires ``unattended_frames`` consecutive
  RELEASED frames with the object still present and still away from the person.
- An object that is never near anyone stays UNKNOWN_DETECTED (reported, never
  claimed attended or unattended — it was neither).
- A stale/dead feed (camera off or detector idle) freezes every watch: no
  transitions, no loss counters, no auto-resolution. The monitor must not lie
  on a dead feed.

Alerts are raised through the same ``AlertManager`` contract the safety
pipeline uses (dedup by root-cause key, cooldown, ack), but with their own
instance so this service stays decoupled from the safety engine.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Dict, List, Optional

from .safety.alert_manager import Alert, AlertManager, AlertSignal

logger = logging.getLogger("astraai.attendance")

UNKNOWN = "UNKNOWN_DETECTED"
POSSIBLY_HELD = "POSSIBLY_HELD"
HELD = "HELD"
RELEASED = "RELEASED"
UNATTENDED = "UNATTENDED"
GONE = "GONE"

_STATES = (UNKNOWN, POSSIBLY_HELD, HELD, RELEASED, UNATTENDED, GONE)


class ObjectWatch:
    """One unknown object followed across frames."""

    def __init__(self, instance_id: str, box: dict, now: int, state: str = UNKNOWN) -> None:
        self.instance_id = instance_id
        self.state = state
        self.box = box
        self.first_seen_ms = now
        self.last_seen_frame = 0
        self.frames_in_state = 0
        self.person_id: Optional[str] = None
        self.transitions: list[dict] = []
        self._append_transition(state, now, "first seen")

    def _append_transition(self, state: str, now: int, reason: str) -> None:
        self.transitions.append({"state": state, "ts": now, "reason": reason})

    def transition(self, state: str, now: int, reason: str) -> dict | None:
        if state == self.state:
            return None
        previous = self.state
        self.state = state
        self.frames_in_state = 0
        self._append_transition(state, now, reason)
        return {"instance_id": self.instance_id, "from": previous, "to": state, "ts": now, "reason": reason}

    def to_dict(self) -> dict:
        return {
            "instanceId": self.instance_id,
            "state": self.state,
            "box": self.box,
            "firstSeenMs": self.first_seen_ms,
            "framesInState": self.frames_in_state,
            "personId": self.person_id,
            "transitions": self.transitions,
        }


def _box(d: dict) -> tuple[int, int, int, int]:
    return int(d["x1"]), int(d["y1"]), int(d["x2"]), int(d["y2"])


def _center(d: dict) -> tuple[int, int]:
    x1, y1, x2, y2 = _box(d)
    return (x1 + x2) // 2, (y1 + y2) // 2


def _in_reach_region(obj: dict, person: dict, arm_reach: float, upper_body: float) -> bool:
    """Is the object inside the person's hand-reachable region?

    The region is the head-shoulders-upper-torso band plus an arm-reach margin
    to each side and above — deliberately NOT the whole person box, so an
    object by the astronaut's legs is never mistaken for a held one.
    """
    px1, py1, px2, py2 = _box(person)
    pw = max(px2 - px1, 1)
    margin = arm_reach * pw
    top = py1 - margin / 2.0
    bottom = py1 + (py2 - py1) * max(0.05, upper_body)
    ox, oy = _center(obj)
    return (px1 - margin) <= ox <= (px2 + margin) and top <= oy <= bottom


class AttendanceMonitor:
    """Polls the detection feed and drives per-object attendance states."""

    def __init__(
        self,
        provider: Callable[[], dict],
        *,
        poll_ms: int = 150,
        held_frames: int = 3,
        unattended_frames: int = 5,
        track_lost_frames: int = 30,
        arm_reach: float = 0.6,
        upper_body: float = 0.45,
        alerts: Optional[AlertManager] = None,
    ) -> None:
        self._provider = provider
        self.poll_ms = max(10, poll_ms)
        self.held_frames = max(1, held_frames)
        self.unattended_frames = max(1, unattended_frames)
        self.track_lost_frames = max(1, track_lost_frames)
        self.arm_reach = arm_reach
        self.upper_body = max(0.05, min(upper_body, 1.0))
        self.alerts = alerts or AlertManager()
        self.watches: Dict[str, ObjectWatch] = {}
        self._task: Optional[asyncio.Task] = None
        self._monitoring = False
        self._tick = 0
        self._last_payload: Optional[dict] = None
        self._events: list[dict] = []
        self._broadcast: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------ control

    def is_monitoring(self) -> bool:
        return self._monitoring

    def set_broadcast(self, fn: Callable[[str], None]) -> None:
        """Wire a per-event sink (main threads event JSON through WS)."""
        self._broadcast = fn

    async def start(self) -> dict:
        if self._monitoring:
            return self.status()
        self._monitoring = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Attendance monitoring started")
        return self.status()

    async def stop(self) -> dict:
        if not self._monitoring:
            return self.status()
        self._monitoring = False
        if self._task is not None:
            self._task.cancel()
            self._task = None
        logger.info("Attendance monitoring stopped")
        return self.status()

    def reset(self) -> None:
        self.watches.clear()
        self._events.clear()
        self.alerts.reset()

    # -------------------------------------------------------------- status

    def status(self) -> dict:
        return {
            "monitoring": self._monitoring,
            "objects": len(self.watches),
            "unattendedCount": sum(1 for w in self.watches.values() if w.state == UNATTENDED),
            "heldCount": sum(1 for w in self.watches.values() if w.state == HELD),
            "thresholds": {
                "heldFrames": self.held_frames,
                "unattendedFrames": self.unattended_frames,
                "trackLostFrames": self.track_lost_frames,
                "armReach": self.arm_reach,
                "upperBody": self.upper_body,
            },
        }

    def latest(self) -> dict:
        return {
            "watches": [w.to_dict() for w in sorted(self.watches.values(), key=lambda w: w.first_seen_ms)],
            "events": list(self._events[-40:]),  # ring buffer for the UI
        }

    async def acknowledge(self, alert_id: str, note: str = "") -> dict:
        alert = self.alerts.acknowledge(alert_id, note=note)
        return {"found": alert is not None, "alert": alert}

    # ----------------------------------------------------------------- loop

    async def _loop(self) -> None:
        while self._monitoring:
            await asyncio.sleep(self.poll_ms / 1000.0)
            try:
                await self.step()
            except Exception as exc:  # noqa: BLE001 - the monitor never dies
                logger.exception("Attendance step failed")
                self._emit({"kind": "ATTENDANCE_ERROR", "severity": "error", "message": str(exc)})

    async def step(self) -> None:
        """One assessment tick. Pure reads fall through to :meth:`_reconcile`."""
        payload = self._provider()
        if not self._is_fresh(payload):
            return
        self._tick += 1
        self._last_payload = payload
        events, now = self._reconcile(payload)
        for ev in events:
            self._emit(ev)

    @staticmethod
    def _is_fresh(payload: dict) -> bool:
        """A payload only drives state when the detector is actively serving
        a frame (camera on, inference fresh)."""
        return bool(payload.get("enabled")) and bool(payload.get("frameWidth"))

    # ------------------------------------------------------------ state sm

    def _reconcile(self, payload: dict) -> tuple[List[dict], int]:
        now = int(time.time() * 1000)
        unknown = payload.get("unknownDetections") or []
        persons = [d for d in (payload.get("detections") or []) if d.get("class_name") == "person"]
        events: list[dict] = []
        seen: set[str] = set()

        for d in unknown:
            instance_id = d.get("instance_id") or f"unknown-anon-{d['x1']}-{d['y1']}"
            seen.add(instance_id)
            watch = self.watches.get(instance_id)
            if watch is None:
                watch = ObjectWatch(instance_id, d, now)
                self.watches[instance_id] = watch
                events.append(self._transition_event(watch.transition(UNKNOWN, now, "detected")))
            watch.last_seen_frame = self._tick
            watch.box = d

            near = self._nearest_person(d, persons)
            near_id = near["id"] if near else None
            self._advance(watch, near, now, events)

        # Expire watches that have vanished from the feed.
        for instance_id, watch in list(self.watches.items()):
            if instance_id in seen:
                continue
            if self._tick - watch.last_seen_frame >= self.track_lost_frames:
                reason = "unattended object left the field of view" if watch.state == UNATTENDED else "track lost"
                events.append(self._transition_event(watch.transition(GONE, now, reason)))
                self.watches.pop(instance_id, None)

        # Reconcile alerts from the current unattended set (dedup/cooldown).
        signals = [
            AlertSignal(
                key=f"attendance-{w.instance_id}",
                level="WARNING",
                title="Unattended unknown object",
                message=f"Unknown object {w.instance_id} was held and left unattended for "
                f"{self.unattended_frames}+ frames.",
                risk_score=0.6,
                confidence=w.box.get("confidence", 0.0),
                object="unknown_object",
                hazard_type="unattended_object",
                recommended_action="Secure the object after use; stow it so it cannot drift.",
            )
            for w in self.watches.values()
            if w.state == UNATTENDED
        ]
        for alert in self.alerts.update(signals, now):
            events.append(self._log_alert(alert))
        return events, now

    def _nearest_person(self, obj: dict, persons: list[dict]) -> Optional[dict]:
        near: Optional[dict] = None
        best = 0.0
        for person in persons:
            if not _in_reach_region(obj, person, self.arm_reach, self.upper_body):
                continue
            px1, py1, px2, py2 = _box(person)
            px, py = _center(person)
            ox, oy = _center(obj)
            dist = ((px - ox) ** 2 + (py - oy) ** 2) ** 0.5
            scale = dist / max((px2 - px1) + (py2 - py1), 1)
            closeness = 1.0 / (1.0 + scale)
            if closeness > best:
                best = closeness
                near = {**person, "id": person.get("instance_id") or f"person-{person['x1']}-{person['y1']}"}
        return near

    def _advance(self, watch: ObjectWatch, near: Optional[dict], now: int, events: list[dict]) -> None:
        watch.frames_in_state += 1
        if near is not None:
            watch.person_id = near["id"]
            if watch.state in (UNKNOWN, POSSIBLY_HELD):
                if watch.state == UNKNOWN:
                    ev = watch.transition(POSSIBLY_HELD, now, "near astronaut hand/head region")
                    if ev:
                        events.append(self._transition_event(ev))
                elif watch.frames_in_state >= self.held_frames:
                    ev = watch.transition(HELD, now, "stays in hand-reach")
                    if ev:
                        events.append(self._transition_event(ev))
            return
        watch.person_id = None
        if watch.state in (HELD, POSSIBLY_HELD):
            ev = watch.transition(RELEASED, now, "left astronaut reach region")
            if ev:
                events.append(self._transition_event(ev))
            return
        if watch.state == RELEASED and watch.frames_in_state >= self.unattended_frames:
            ev = watch.transition(UNATTENDED, now, "unattended after release")
            if ev:
                events.append(self._transition_event(ev))

    # --------------------------------------------------------------- events

    def _transition_event(self, ev: dict | None) -> dict:
        if ev is None:
            return {}
        return {
            "kind": "ATTENDANCE_TRANSITION",
            "severity": "warn" if ev["to"] in (UNATTENDED, RELEASED) else "info",
            "instanceId": ev["instance_id"],
            "from": ev["from"],
            "to": ev["to"],
            "ts": ev["ts"],
            "reason": ev["reason"],
        }

    def _log_alert(self, alert: Alert) -> dict:
        if getattr(alert, "resolved", False):
            kind, severity, message = "ATTENDANCE_ALERT_RESOLVED", "info", f"Alert resolved: {alert.title}"
        else:
            kind, severity, message = "ATTENDANCE_ALERT_RAISED", "warn", f"{alert.level} — {alert.message}"
        return {
            "kind": kind,
            "severity": severity,
            "message": message,
            "level": alert.level,
            "alertId": alert.id,
            "object": alert.object,
            "ts": alert.updated_at,
        }

    def _emit(self, event: dict) -> None:
        if not event:
            return
        self._events.append(event)
        logger.info("attendance: %s %s -> %s", event.get("kind"), event.get("from", ""), event.get("to", ""))
        if self._broadcast is not None:
            self._broadcast(event)

    def enqueue(self, event: dict) -> None:
        self._events.append(event)
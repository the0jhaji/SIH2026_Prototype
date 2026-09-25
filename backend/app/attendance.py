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

KNOWN objects (a bottle, a tool) are watched too, on a separate chain, because
the reported failure was never an unknown object at all:

    ATTENDED <-> UNATTENDED, with OBJECT_INSIDE_BOX on containment

- Only classes in ``tracked_classes`` are watched; ``person`` is excluded by
  definition because attendance is about the *thing* being left, not the crew.
- ATTENDED while any person is within ``proximity`` (a fraction of the frame
  diagonal) of the object centre — proximity, not arm-reach, because a tool
  resting on a bench right beside the astronaut is still attended.
- UNATTENDED once the object has been person-free for ``unattended_timeout_ms``
  of *wall clock*, not a frame count: at the 2-4 AI FPS this host actually
  achieves, a 5-frame counter is 1.2-2.5s and swings with machine load.
- The known chain never passes through HELD, so an object that was already in
  the container before the monitor started still reaches UNATTENDED.
- Containment is a geometric claim (fraction of the object box inside a
  container box) reported as OBJECT_INSIDE_BOX; it is deliberately *not* an
  attendance claim, and a contained object can be attended or unattended.

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
#: Event kind for containment. Deliberately NOT a state: "is it in the box" and
#: "is anybody minding it" are independent facts, and forcing both into one state
#: field made a contained+attended object thrash. Containment lives in
#: ``ObjectWatch.inside_container`` and is announced as its own event.
IN_CONTAINER = "OBJECT_INSIDE_BOX"
#: Known-object chain: a person is close enough to be considered minding it.
ATTENDED = "ATTENDED"

_STATES = (UNKNOWN, POSSIBLY_HELD, HELD, RELEASED, UNATTENDED, GONE, ATTENDED)

#: Object->watch IoU floor for re-attaching a known-class detection to its watch.
#: Mirrors the tracker's own match floor so both layers agree on "same object".
_WATCH_IOU = 0.3


def _iou(a: dict, b: dict) -> float:
    ax1, ay1, ax2, ay2 = _box(a)
    bx1, by1, bx2, by2 = _box(b)
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _containment_score(obj: dict, container: dict) -> float:
    """Fraction of the *object* box that lies inside the *container* box.

    Object-relative on purpose: a big open container with a small object still
    counts as "in", and a small container swallowing a huge detection does not.
    """
    ox1, oy1, ox2, oy2 = _box(obj)
    cx1, cy1, cx2, cy2 = _box(container)
    ix = max(0, min(ox2, cx2) - max(ox1, cx1))
    iy = max(0, min(oy2, cy2) - max(oy1, cy1))
    inter = ix * iy
    area = max(0, ox2 - ox1) * max(0, oy2 - oy1)
    return (inter / area) if area > 0 else 0.0


class ObjectWatch:
    """One object followed across frames (unknown proposal or known class)."""

    def __init__(
        self,
        instance_id: str,
        box: dict,
        now: int,
        state: str = UNKNOWN,
        is_unknown: Optional[bool] = None,
    ) -> None:
        self.instance_id = instance_id
        self.state = state
        self.box = box
        self.first_seen_ms = now
        self.last_seen_frame = 0
        self.frames_in_state = 0
        self.person_id: Optional[str] = None
        self.transitions: list[dict] = []
        # --- known-object chain bookkeeping --------------------------------
        #: driven by provenance, not by the starting state: a known-class watch
        #: starts in UNKNOWN but must not be treated as an unknown proposal.
        self.is_unknown = (state == UNKNOWN) if is_unknown is None else bool(is_unknown)
        #: wall-clock ms at which the object was last seen with NO person near it
        self.person_free_since_ms: Optional[int] = None
        #: the container it was found inside, plus the geometry that proved it
        self.container_id: Optional[str] = None
        self.container_class: Optional[str] = None
        self.containment_score: float = 0.0
        self.inside_container: bool = False
        self._append_transition(state, now, "first seen")

    @property
    def class_name(self) -> str:
        return str(self.box.get("class_name", "unknown_object"))

    @property
    def person_free_ms(self) -> int:
        if self.person_free_since_ms is None:
            return 0
        return max(0, int(time.time() * 1000) - self.person_free_since_ms)

    def to_dict(self) -> dict:
        return {
            "instanceId": self.instance_id,
            "state": self.state,
            "box": self.box,
            "className": self.class_name,
            "isUnknown": self.is_unknown,
            "firstSeenMs": self.first_seen_ms,
            "framesInState": self.frames_in_state,
            "personId": self.person_id,
            "personFreeMs": self.person_free_ms,
            "insideContainer": self.inside_container,
            "containerId": self.container_id,
            "containerClass": self.container_class,
            "containmentScore": round(self.containment_score, 4),
            "transitions": self.transitions,
        }

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
        unattended_timeout_ms: int = 2000,
        proximity: float = 0.18,
        containment: float = 0.6,
        container_classes: tuple[str, ...] = (),
        tracked_classes: tuple[str, ...] = (),
        alerts: Optional[AlertManager] = None,
    ) -> None:
        self._provider = provider
        self.poll_ms = max(10, poll_ms)
        self.held_frames = max(1, held_frames)
        self.unattended_frames = max(1, unattended_frames)
        self.track_lost_frames = max(1, track_lost_frames)
        self.arm_reach = arm_reach
        self.upper_body = max(0.05, min(upper_body, 1.0))
        self.unattended_timeout_ms = max(0, int(unattended_timeout_ms))
        self.proximity = max(0.0, proximity)
        self.containment = max(0.0, min(containment, 1.0))
        self.container_classes = frozenset(container_classes or ())
        self.tracked_classes = frozenset(tracked_classes or ())
        self.alerts = alerts or AlertManager()
        self.watches: Dict[str, ObjectWatch] = {}
        self._task: Optional[asyncio.Task] = None
        self._monitoring = False
        self._tick = 0
        self._last_payload: Optional[dict] = None
        self._events: list[dict] = []
        self._broadcast: Optional[Callable[[str], None]] = None
        self._auto_seq = 0
        self._frame_diag = 1.0

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
            "inContainerCount": sum(1 for w in self.watches.values() if w.inside_container),
            "thresholds": {
                "heldFrames": self.held_frames,
                "unattendedFrames": self.unattended_frames,
                "trackLostFrames": self.track_lost_frames,
                "armReach": self.arm_reach,
                "upperBody": self.upper_body,
                "unattendedTimeoutMs": self.unattended_timeout_ms,
                "proximity": self.proximity,
                "containment": self.containment,
                "containerClasses": sorted(self.container_classes),
                "trackedClasses": sorted(self.tracked_classes),
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
        # Proximity is expressed against the frame diagonal, so the threshold
        # means the same thing at 640x360 and 1280x720.
        fw = float(payload.get("frameWidth") or 0.0)
        fh = float(payload.get("frameHeight") or 0.0)
        if fw > 0 and fh > 0:
            self._frame_diag = (fw * fw + fh * fh) ** 0.5
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
        known = payload.get("detections") or []
        persons = [d for d in known if d.get("class_name") == "person"]
        containers = [d for d in known if d.get("class_name") in self.container_classes]
        # Known objects we are willing to call unattended. `person` is excluded by
        # construction: the crew is not an unattended object.
        watchable = [d for d in known if d.get("class_name") in self.tracked_classes]
        events: list[dict] = []
        seen: set[str] = set()

        # --- unknown-object chain: hand-off semantics, unchanged --------------
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

        # --- known-object chain: presence, containment, attendance ------------
        for d in watchable:
            watch = self._match_known_watch(d)
            seen.add(watch.instance_id)
            watch.last_seen_frame = self._tick
            watch.box = d
            self._advance_known(watch, d, persons, containers, now, events)

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
                title="Unattended object",
                message=(
                    f"Unknown object {w.instance_id} was held and left unattended for "
                    f"{self.unattended_frames}+ frames."
                    if w.is_unknown
                    else (
                        f"{w.class_name} ({w.instance_id}) was left with no astronaut in reach"
                        + (
                            f" for {w.person_free_ms / 1000.0:.1f}s"
                            if w.person_free_ms >= self.unattended_timeout_ms
                            else f" (policy: alert after {self.unattended_timeout_ms / 1000.0:.1f}s)"
                        )
                    )
                ),
                risk_score=0.6,
                confidence=w.box.get("confidence", 0.0),
                object=w.class_name,
                hazard_type="unattended_object",
                recommended_action="Secure the object after use; stow it so it cannot drift.",
            )
            for w in self.watches.values()
            if w.state == UNATTENDED
        ]
        for alert in self.alerts.update(signals, now):
            events.append(self._log_alert(alert))
        return events, now

    def _match_known_watch(self, d: dict) -> ObjectWatch:
        """Re-attach a known-class detection to its existing watch by class + IoU.

        Known detections carry no ``instance_id`` (the tracker only mints ids for
        ``unknown_object``), so identity is recovered here with the same IoU floor
        the tracker uses. A detection that matches nothing becomes a new watch.
        """
        cls = d.get("class_name")
        best: Optional[ObjectWatch] = None
        best_iou = _WATCH_IOU
        for watch in self.watches.values():
            if watch.is_unknown or watch.class_name != cls:
                continue
            score = _iou(watch.box, d)
            if score >= best_iou:
                best, best_iou = watch, score
        if best is not None:
            return best
        self._auto_seq += 1
        instance_id = f"{cls}#{self._auto_seq}"
        watch = ObjectWatch(instance_id, d, now=int(time.time() * 1000), state=UNKNOWN, is_unknown=False)
        self.watches[instance_id] = watch
        return watch

    def _advance_known(
        self,
        watch: ObjectWatch,
        d: dict,
        persons: list[dict],
        containers: list[dict],
        now: int,
        events: list[dict],
    ) -> None:
        """Containment + attendance for a KNOWN object. Never requires HELD."""
        watch.frames_in_state += 1

        # Containment is geometry, reported independently of attendance.
        best_container = None
        best_score = 0.0
        for c in containers:
            score = _containment_score(d, c)
            if score > best_score:
                best_container, best_score = c, score
        inside = best_container is not None and best_score >= self.containment
        if inside:
            watch.container_id = (
                f"container-{best_container['x1']}-{best_container['y1']}"
                if not best_container.get("instance_id")
                else best_container["instance_id"]
            )
            watch.container_class = best_container.get("class_name")
        watch.containment_score = best_score if inside else 0.0
        if inside and not watch.inside_container:
            watch.inside_container = True
            reason = (
                f"inside {best_container.get('class_name')} "
                f"(containment={best_score:.2f} >= {self.containment:.2f})"
            )
            watch._append_transition(IN_CONTAINER, now, reason)
            events.append(
                self._container_event(now, watch, best_score, best_container.get("class_name"), reason)
            )
        elif not inside and watch.inside_container:
            watch.inside_container = False
            watch.container_id = None
            watch.container_class = None
            watch.containment_score = 0.0

        # Attendance: is anybody close enough to be minding it?
        near = self._nearest_person_proximity(d, persons)
        if near is not None:
            watch.person_id = near["id"]
            watch.person_free_since_ms = None
            if watch.state != ATTENDED:
                ev = watch.transition(ATTENDED, now, "person within proximity")
                if ev:
                    events.append(self._transition_event(ev))
            return

        watch.person_id = None
        if watch.person_free_since_ms is None:
            watch.person_free_since_ms = now
        free_ms = now - watch.person_free_since_ms
        if watch.state == ATTENDED:
            ev = watch.transition(UNATTENDED, now, "person left; nobody in proximity")
            if ev:
                events.append(self._transition_event(ev))
            return
        if watch.state != UNATTENDED and free_ms >= self.unattended_timeout_ms:
            ev = watch.transition(
                UNATTENDED,
                now,
                f"unattended for {free_ms}ms (>= {self.unattended_timeout_ms}ms timeout)",
            )
            if ev:
                events.append(self._transition_event(ev))

    def _nearest_person_proximity(self, obj: dict, persons: list[dict]) -> Optional[dict]:
        """Nearest person whose centre is within ``proximity`` of the frame diagonal.

        Proximity (not arm-reach) on purpose: a tool resting on the bench next to
        the astronaut is still attended, even though it never touches a hand.
        """
        if not persons:
            return None
        ox, oy = _center(obj)
        near: Optional[dict] = None
        best = float("inf")
        for person in persons:
            px, py = _center(person)
            dist = ((px - ox) ** 2 + (py - oy) ** 2) ** 0.5
            if dist < best:
                best, near = dist, {**person, "id": person.get("instance_id") or f"person-{person['x1']}-{person['y1']}"}
        if near is None:
            return None
        limit = self.proximity * self._frame_diag
        return near if best <= limit else None

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

    def _container_event(
        self, ts: int, watch: ObjectWatch, score: float, container_class: Optional[str], reason: str
    ) -> dict:
        """OBJECT_INSIDE_BOX: a distinct event, not an attendance verdict.

        The UI and the WS stream need to see containment on its own so a demo can
        show the object landing in the box, and so the unattended timer that follows
        is explainable by the geometry that started it.
        """
        return {
            "kind": IN_CONTAINER,
            "severity": "info",
            "instanceId": watch.instance_id,
            "objectClass": watch.class_name,
            "containerClass": container_class,
            "containmentScore": round(score, 4),
            "ts": ts,
            "reason": reason,
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
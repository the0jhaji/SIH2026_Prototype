"""Event-grounded ACTIVITY perception source (``ACTIVITY_BACKEND=interaction``).

The bridge the box experiment was missing. The semantic hand/object tracker
(``ai.pipeline.interaction.InteractionTracker``) has always produced the real
action evidence — ``*_MOVED`` (an object physically displaced over consecutive
frames), ``*_PLACED`` (it came to rest inside the target area) and
``HAND_NEAR_*`` — but the backend only ever consumed *object presence*
(``LiveActivityPerception``: a step advanced when the expected objects were
merely visible). This source runs the tracker over the ``DetectionService``
feed and maps its events to each step's ``expectedEvents`` in the canonical
experiment, so:

    APPROACH    fires on ``person`` presence,
    OPEN_BOX    fires on the container being moved,
    PICK_RED    fires on a red-box *move episode*,
    PLACE_RED   fires on a red-box *placement episode*,
    COMPLETE    fires once both boxes have been placed at least once.

Mere visibility never advances anything: nothing but a tracker-confirmed
motion/placement can satisfy a PICK or a PLACE. Evidence is data
(``experiment/experiment.json``), never code — a procedure that declares its
own ``expectedEvents`` works unchanged.

Design rules
------------
* **Perception observes, the state machine decides.** This source emits the
  activity of the *earliest* step (at or after the session pointer) whose
  evidence is satisfied. When that is not the expected step the emission still
  goes out, and the state machine classifies it as WRONG_OBJECT /
  WRONG_SEQUENCE / OUT_OF_SEQUENCE. The source never decides validity.
* **Every physical episode credits exactly one step.** Evidence is counted,
  not latched: the tracker emits at most one ``*_MOVED`` per motion episode
  and one ``*_PLACED`` per placement episode, so a step is satisfied only
  while it holds an *unconsumed* episode, and firing consumes exactly the
  episodes it used. Holding a box up, or replaying a wrong action forever,
  therefore re-reports nothing; and an out-of-sequence pick does not consume
  the episode the *correct* step would later need.
* **Temporal confirmation is layered.** The tracker itself needs consecutive
  frames (``min_move_frames`` / ``settle_frames``) before it emits anything;
  the source then requires its evidence to hold for ``confirm_polls`` polls of
  one stable best candidate; the state engine applies its own frame
  confirmation on top.
* **A stale feed blocks emission** exactly like ``LiveActivityPerception``:
  a disabled/errored detector or a frozen inference (camera stopped) never
  advances or completes the experiment.
* **Honest limits.** No hand landmarks are available on this host (MediaPipe
  has no model installed), so ``HAND_NEAR_*`` is never produced and
  ``*_MOVED`` / ``*_PLACED`` are object-side only — "held" is not verified.
  A container lid is not observable, so OPEN_BOX is grounded on the container
  moving; opening a box can also jiggle its contents, which may be credited as
  a content move. Both limitations are documented rather than hidden.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional

from .schemas import Detection, ExperimentDef, StepDef

#: Evidence kinds understood by this source (the experiment.json contract).
PRESENT = "PRESENT"
MOVED = "MOVED"
PLACED = "PLACED"
EVIDENCE_KINDS = (PRESENT, MOVED, PLACED)

#: Class whose box defines where a PLACED object has to come to rest.
DEFAULT_TARGET_CLASS = "target_area"


def tracker_prefixes(experiment: ExperimentDef) -> dict[str, str]:
    """class_name → event-prefix map for the interaction tracker, derived from
    the experiment's own object table.

    Only roles ``container`` and ``handled-object`` are tracked for motion: the
    actor (``person``) and the destination region (``target_area``) are never
    treated as movable objects, they are presence/region evidence. Prefixes are
    the class name's first token uppercased (``red_box`` → ``RED``), so a step
    naming a class lines up with the event names the tracker emits for it.
    Falls back to the built-in demo pair when the experiment declares none.
    """
    from ai.pipeline.interaction.events import OBJECT_TO_PREFIX

    out: dict[str, str] = {}
    for obj in experiment.objects or []:
        class_id = obj.get("id")
        if obj.get("role") in ("container", "handled-object") and class_id:
            out[str(class_id)] = str(class_id).split("_")[0].upper()
    return out or dict(OBJECT_TO_PREFIX)


@dataclass
class ObjectFacts:
    """Counted, per-object evidence. Episodes, not latched booleans.

    ``*_consumed`` marks episodes already credited to a step emission, so a
    step that fires cannot be re-fired by the same physical action, and the
    episode is still available to whichever step legitimately needs it next.
    """

    present_edges: int = 0
    present_consumed: int = 0
    present_confidence: float = 0.0
    moved_episodes: int = 0
    moved_consumed: int = 0
    moved_confidence: float = 0.0
    placed_episodes: int = 0
    placed_consumed: int = 0
    placed_confidence: float = 0.0


class InteractionActivityPerception:
    """Camera-grounded, event-grounded activity source."""

    name = "interaction"

    def __init__(
        self,
        experiment: ExperimentDef,
        detection_service,
        *,
        poll_ms: int = 700,
        conf_threshold: float = 0.5,
        stale_after_ms: int = 5000,
        confirm_polls: int = 2,
        target_class: str = DEFAULT_TARGET_CLASS,
        target_box: Optional[tuple[float, float, float, float]] = None,
        current_index: Optional[Callable[[], int]] = None,
    ) -> None:
        from ai.pipeline.interaction import InteractionConfig, InteractionTracker

        self.experiment = experiment
        self.detection_service = detection_service
        self.poll_ms = poll_ms
        self.conf_threshold = conf_threshold
        self.stale_after_ms = stale_after_ms
        self.confirm_polls = max(1, confirm_polls)
        self.target_class = target_class
        #: Normalized destination region. ``None`` means no shipped detector can
        #: see the target, so PLACED is ungrounded rather than assumed.
        self.target_box = target_box
        self._target_box_source = "configured" if target_box else "detector-or-none"
        self._current_index = current_index or (lambda: 0)
        self.class_prefixes = tracker_prefixes(experiment)
        self.tracker = InteractionTracker(InteractionConfig(class_prefixes=self.class_prefixes))
        self._facts: dict[str, ObjectFacts] = {}
        self._present: dict[str, float] = {}
        self._present_prev: set[str] = set()
        self._pending_id: Optional[str] = None
        self._pending_count = 0
        #: Steps already emitted whose evidence was entirely cumulative, so they
        #: must never be offered again (see _evaluate).
        self._latched: set[str] = set()
        self._last_events: deque = deque(maxlen=12)

    # -------------------------------------------------------------------- api

    def reset(self) -> None:
        """Drop all accumulated evidence for a fresh run (called on start)."""
        self._facts.clear()
        self._present.clear()
        self._present_prev.clear()
        self._pending_id = None
        self._pending_count = 0
        self._latched.clear()
        self._last_events.clear()
        self.tracker.reset()

    def _target_area_source(self) -> str:
        if self.target_box is not None:
            return "configured"
        # Read without inserting: a status poll must not create evidence.
        fact = self._facts.get(self.target_class)
        return "detector" if fact and fact.present_edges else "none"

    def status(self) -> dict:
        return {
            "name": self.name,
            "trackedClasses": list(self.class_prefixes),
            "targetClass": self.target_class,
            "targetAreaSource": self._target_area_source(),
            "placedGrounded": self.target_box is not None,
            "facts": {
                cls: {
                    "presentEdges": f.present_edges,
                    "movedEpisodes": f.moved_episodes,
                    "placedEpisodes": f.placed_episodes,
                }
                for cls, f in self._facts.items()
            },
            "events": list(self._last_events),
            "trackedObjects": len(self.tracker.object_tracks),
        }

    # ---------------------------------------------------------------- evidence

    def _fact(self, class_name: str) -> ObjectFacts:
        return self._facts.setdefault(class_name, ObjectFacts())

    def _counters(self, kind: str, class_name: str) -> tuple[int, int, float]:
        fact = self._facts.get(class_name)
        if fact is None:
            return (0, 0, 0.0)
        if kind == PRESENT:
            return (fact.present_edges, fact.present_consumed, fact.present_confidence)
        if kind == MOVED:
            return (fact.moved_episodes, fact.moved_consumed, fact.moved_confidence)
        return (fact.placed_episodes, fact.placed_consumed, fact.placed_confidence)

    def _rule_objects(self, rule: dict) -> list[str]:
        raw = rule.get("object") or rule.get("objects")
        return [raw] if isinstance(raw, str) else list(raw or [])

    def _rule_match(
        self, kind: str, objects: list[str], fresh: bool
    ) -> Optional[tuple[str, int, float]]:
        """Best object satisfying a rule: ``(class, episodes, confidence)``.

        A ``fresh`` rule (the default) needs an unconsumed episode — that is
        what makes firing edge-triggered. A cumulative rule (``fresh: false``,
        used by terminal steps such as COMPLETE) only needs the episode to have
        happened at all, because the action it describes was performed by an
        earlier step.
        """
        best: Optional[tuple[str, int, float]] = None
        for obj in objects:
            episodes, consumed, confidence = self._counters(kind, obj)
            ok = episodes > consumed if fresh else episodes > 0
            if ok and (best is None or episodes > best[1]):
                best = (obj, episodes, confidence)
        return best

    def _step_evidence(self, step: StepDef) -> Optional[tuple[float, list[tuple[str, str, int]]]]:
        """``(confidence, uses)`` when every rule of ``step`` holds, else None.

        ``uses`` is the ``(kind, class, episodes)`` list the caller consumes
        when the step actually fires.
        """
        rules = step.expectedEvents or []
        if not rules:
            return None
        confs: list[float] = []
        uses: list[tuple[str, str, int]] = []
        for rule in rules:
            kind = rule.get("event")
            if kind not in EVIDENCE_KINDS:
                return None
            objects = self._rule_objects(rule)
            if not objects:
                return None
            fresh = rule.get("fresh", True)
            match = self._rule_match(kind, objects, bool(fresh))
            if match is None:
                return None
            obj, episodes, confidence = match
            confs.append(confidence)
            if fresh:
                uses.append((kind, obj, episodes))
        return (min(confs), uses)

    def _consume(self, uses: list[tuple[str, str, int]]) -> None:
        """Spend exactly one episode per matched rule.

        A step consumes *one* physical episode, never every episode seen so
        far: confirmation waits at least ``confirm_polls`` frames, by which time
        later steps' episodes may already exist, and marking them consumed here
        would starve them (OPEN_BOX silently swallowing the PICK_RED move).
        """
        for kind, obj, _episodes in uses:
            fact = self._fact(obj)
            if kind == PRESENT:
                fact.present_consumed += 1
            elif kind == MOVED:
                fact.moved_consumed += 1
            else:
                fact.placed_consumed += 1

    def _candidate(self) -> Optional[tuple[StepDef, float, list[tuple[str, str, int]]]]:
        """Earliest step at/after the pointer with satisfied evidence."""
        current = self._current_index()
        for index in range(max(0, current), len(self.experiment.steps)):
            step = self.experiment.steps[index]
            if step.id in self._latched:
                continue
            evidence = self._step_evidence(step)
            if evidence is not None:
                return (step, evidence[0], evidence[1])
        return None

    def _evaluate(self, now: int) -> Optional[Detection]:
        candidate = self._candidate()
        if candidate is None:
            self._pending_id = None
            self._pending_count = 0
            return None
        step, confidence, uses = candidate
        # Temporal confirmation on one stable candidate: if the best step
        # changes between polls the count restarts, so a flapping detection
        # never confirms.
        if step.id == self._pending_id:
            self._pending_count += 1
        else:
            self._pending_id = step.id
            self._pending_count = 1
        if self._pending_count < self.confirm_polls:
            return None
        self._pending_id = None
        self._pending_count = 0
        self._consume(uses)
        if not uses:
            # Every rule was cumulative, so there is nothing to spend: without
            # a latch the same terminal step would be re-offered on every poll
            # and, when the state machine refuses it, emitted forever.
            self._latched.add(step.id)
        return Detection(activity=step.activity, confidence=round(confidence, 3), ts=now)

    # ------------------------------------------------------------------ intake

    def _ingest(self, latest: dict) -> None:
        from ai.pipeline.detections import Box, ObjectDetection

        dets = latest.get("detections") or []
        frame_w = latest.get("frameWidth")
        frame_h = latest.get("frameHeight")
        if not frame_w or not frame_h:
            return
        now = int(time.time() * 1000)
        present: dict[str, float] = {}
        tracker_input: list[ObjectDetection] = []
        for det in dets:
            cls = det.get("class_name")
            if not cls:
                continue
            try:
                x1, y1 = int(det["x1"]), int(det["y1"])
                x2, y2 = int(det["x2"]), int(det["y2"])
            except (KeyError, TypeError, ValueError):
                continue
            confidence = float(det.get("confidence", 0.0))
            if confidence >= self.conf_threshold:
                present[cls] = max(present.get(cls, 0.0), confidence)
            # The tracker needs the tracked objects *and* the target region;
            # it ignores any other class internally.
            if cls in self.class_prefixes or cls == self.target_class:
                tracker_input.append(
                    ObjectDetection(
                        class_name=cls,
                        confidence=confidence,
                        bounding_box=Box(x1, y1, max(0, x2 - x1), max(0, y2 - y1)),
                        timestamp=now,
                    )
                )
        # Presence is edge-counted: one APPROACH per arrival, never per frame.
        for cls, confidence in present.items():
            if cls not in self._present_prev:
                fact = self._fact(cls)
                fact.present_edges += 1
                fact.present_confidence = confidence
        self._present_prev = set(present)
        self._present = present

        if self.target_box is not None and not any(
            d.class_name == self.target_class for d in tracker_input
        ):
            # The destination is a configured fixture region, not a detection.
            nx1, ny1, nx2, ny2 = self.target_box
            tracker_input.append(
                ObjectDetection(
                    class_name=self.target_class,
                    confidence=1.0,
                    bounding_box=Box(
                        int(nx1 * frame_w),
                        int(ny1 * frame_h),
                        int((nx2 - nx1) * frame_w),
                        int((ny2 - ny1) * frame_h),
                    ),
                    timestamp=now,
                )
            )

        for event in self.tracker.update(tracker_input, [], (frame_w, frame_h), now):
            fact = self._fact(event.object_class)
            if event.name.endswith("_MOVED"):
                fact.moved_episodes += 1
                fact.moved_confidence = max(fact.moved_confidence, event.confidence)
            elif event.name.endswith("_PLACED") and event.in_target_area:
                fact.placed_episodes += 1
                fact.placed_confidence = max(fact.placed_confidence, event.confidence)
            self._last_events.append(event.to_dict())

    async def detections(self, max_idle_polls: Optional[int] = None) -> AsyncIterator[Detection]:
        idle = 0
        while True:
            await asyncio.sleep(self.poll_ms / 1000.0)
            latest = self.detection_service.latest()
            now = int(time.time() * 1000)
            if not latest or not latest.get("enabled"):
                idle += 1
            elif latest.get("inferenceStatus") != "ok":
                idle += 1
            elif latest.get("lastInferenceMs") is None or (
                now - latest["lastInferenceMs"] > self.stale_after_ms
            ):
                idle += 1
            else:
                self._ingest(latest)
                detection = self._evaluate(now)
                if detection is None:
                    idle += 1
                else:
                    idle = 0
                    yield detection
            if max_idle_polls is not None and idle >= max_idle_polls:
                return

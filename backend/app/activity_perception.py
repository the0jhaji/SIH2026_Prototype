"""Pluggable ACTIVITY perception stage (Phase 5C runtime bridge).

This is the seam where the state machine's detections come from. Every source
in this module emits exactly the ``Detection`` shape the state machine already
consumes, so swapping the source never touches decision-making.

Implementations:
  * ``LiveActivityPerception`` (default, ``ACTIVITY_BACKEND=live``): the
    camera-grounded source. It polls the object-detection service and only
    emits a ``Detection`` when the currently expected step's
    ``expectedObjects`` are all present on a fresh frame — the experiment
    advances on what is actually in front of the camera, nothing scripted.
  * ``MockActivityPerception`` (``ACTIVITY_BACKEND=mock``): deterministic,
    **derived from the loaded experiment definition itself** — the correct
    steps plus a fixed, experiment-agnostic set of planted mistakes so a run
    exercises every classification outcome. It is a mock; it never claims to
    interpret camera frames.
  * ``SimulatedPerception`` (``ACTIVITY_BACKEND=sim``): the original scripted
    feed, kept for tests and backwards compatibility.

A real activity-recognition model plugs in at this same seam later (same
Detection shape) — no state-machine change required.
"""

import asyncio
import time
from typing import AsyncIterator, Callable, List, Optional

from .experiment import expected_step
from .schemas import Detection, ExperimentDef, StepDef

UNKNOWN_ACTIVITY = "UNKNOWN_GESTURE"


def standard_plan(experiment: ExperimentDef, poll_ms: int) -> List[dict]:
    """Deterministic detection timeline derived from ``experiment`` data.

    Emits the correct step detections in order, plus one planted mistake per
    completed step: an out-of-sequence later step, a repeated step, a
    low-confidence expected step, or an unknown activity (rotating by index).
    The final step runs clean so the run ends COMPLETED.
    """
    steps = experiment.steps
    plan: List[dict] = []

    def detection(activity: str, confidence: float) -> dict:
        return {
            "activity": activity,
            "confidence": round(confidence, 2),
            "delay_ms": poll_ms,
        }

    for index, step in enumerate(steps):
        plan.append(detection(step.activity, 0.95))
        if index >= len(steps) - 1:
            break
        mistake = index % 4
        if mistake == 0:
            later = steps[min(index + 2, len(steps) - 1)]
            plan.append(detection(later.activity, 0.9))
        elif mistake == 1:
            plan.append(detection(steps[0].activity, 0.97))
        elif mistake == 2:
            plan.append(detection(steps[index + 1].activity, 0.42))
        else:
            plan.append(detection(UNKNOWN_ACTIVITY, 0.8))
    return plan


class MockActivityPerception:
    """Deterministic stand-in activity source driven by the loaded experiment.

    Big and unmissable: this is a **mock**. It cycles the experiment's own
    steps (data) with planted mistakes so the full state machine runs
    end-to-end without any real vision.
    """

    name = "mock-activity"

    def __init__(
        self,
        experiment: ExperimentDef,
        poll_ms: int,
        plan: Optional[List[dict]] = None,
    ) -> None:
        self.experiment = experiment
        self.poll_ms = poll_ms
        self.plan = plan if plan is not None else standard_plan(experiment, poll_ms)

    async def detections(self) -> AsyncIterator[Detection]:
        for item in self.plan:
            await asyncio.sleep(item["delay_ms"] / 1000.0)
            yield Detection(
                activity=item["activity"],
                confidence=item["confidence"],
                ts=int(time.time() * 1000),
            )


class LiveActivityPerception:
    """Camera-grounded activity source (``ACTIVITY_BACKEND=live``).

    Feeds the state machine from **what is actually visible on camera**: it
    polls the object-detection service (``latest()``) and only emits a
    Detection when the currently expected step's ``expectedObjects`` are all
    present on a fresh frame at or above ``conf_threshold``. Nothing is
    scripted — if the camera is off, the detector is disabled/errored, or no
    frame has arrived within ``stale_after_ms``, the experiment simply waits.

    The visible objects map to the step's activity straight from the canonical
    experiment definition, so step 2 (OPEN_BOX) only fires when the
    ``experiment_box`` is seen and step 6 (PLACE_YELLOW) needs both
    ``yellow_box`` and ``target_area``. A step with an empty
    ``expectedObjects`` list (legacy demo definitions) never fires live —
    object hiding is explicit, not guessed. Emission is edge-triggered: each
    expected step fires at most once, so holding an object in view never
    repeats a step. Because only the *expected* step can emit, live mode is
    intentionally silent about repeated or out-of-sequence actions — the mock
    source is the demo that exercises every classification outcome.
    """

    name = "live"

    def __init__(
        self,
        experiment: ExperimentDef,
        detection_service,
        *,
        poll_ms: int = 700,
        conf_threshold: float = 0.5,
        stale_after_ms: int = 5000,
        current_index: Optional[Callable[[], int]] = None,
    ) -> None:
        self.experiment = experiment
        self.detection_service = detection_service
        self.poll_ms = poll_ms
        self.conf_threshold = conf_threshold
        self.stale_after_ms = stale_after_ms
        self._current_index = current_index or (lambda: 0)
        self._fired: set[str] = set()

    def reset(self) -> None:
        """Clear per-step state so ``service.start()`` begins a clean run."""
        self._fired.clear()

    def _step_fully_visible(self, step: StepDef, dets: List[dict]) -> Optional[float]:
        """Best confidence when every required object is visible, else None.

        ``expectedObjects == []`` means "nothing is required to be visible",
        which is treated as not-verifiable: it never fires.
        """
        required = step.expectedObjects or []
        if not required:
            return None
        best: List[float] = []
        for obj in required:
            confs = [d["confidence"] for d in dets if d.get("class_name") == obj]
            if not confs:
                return None
            best.append(max(confs))
        min_conf = min(best)
        return min_conf if min_conf >= self.conf_threshold else None

    async def detections(self, max_idle_polls: Optional[int] = None) -> AsyncIterator[Detection]:
        """Emit step detections. ``max_idle_polls`` bounds how many consecutive
        non-emitting polls run before the iterator ends (tests; production
        leaves it None and keeps polling forever)."""
        idle = 0
        while True:
            await asyncio.sleep(self.poll_ms / 1000.0)
            latest = self.detection_service.latest()
            now = int(time.time() * 1000)
            if not latest or not latest.get("enabled"):
                idle += 1
            elif latest.get("inferenceStatus") != "ok":
                idle += 1
            elif latest.get("lastInferenceMs") is None or now - latest["lastInferenceMs"] > self.stale_after_ms:
                idle += 1
            else:
                dets = latest.get("detections") or []
                step = expected_step(self.experiment, self._current_index())
                confidence = self._step_fully_visible(step, dets) if step is not None else None
                if step is None or confidence is None or step.id in self._fired:
                    idle += 1
                else:
                    idle = 0
                    self._fired.add(step.id)
                    yield Detection(
                        activity=step.activity,
                        confidence=round(confidence, 3),
                        ts=now,
                    )
            if max_idle_polls is not None and idle >= max_idle_polls:
                return
"""Tests for the event-grounded ``InteractionActivityPerception``
(``ACTIVITY_BACKEND=interaction``).

The point of this source is that **visibility is not an action**: a box sitting
in frame proves nothing about whether it was picked up or placed. Every test
below therefore feeds *moving* synthetic frames through the real
``ai.pipeline.interaction.InteractionTracker`` and asserts on the activities the
source emits and the classifications the authoritative ``ExperimentSession``
derives from them.
"""

import asyncio
import time

from app.experiment import load_active_experiment
from app.interaction_perception import InteractionActivityPerception, tracker_prefixes
from app.schemas import ExperimentDef, StepDef
from app.state_machine import ExperimentSession

SIZE = 40
# x, y, w, h — generous, so settled boxes are unambiguously inside it.
TARGET = (700, 300, 400, 350)
PERSON = (120, 260)
RED_HOME = (420, 430)
YELLOW_HOME = (490, 430)
RED_TARGET = (800, 500)
YELLOW_TARGET = (1000, 500)

#: The whole scene at rest, before anything happens.
#:
#: Only person, red_box and yellow_box appear: those are the classes real
#: detectors actually emit (the custom model's ``.names`` lists red/yellow, the
#: heuristic detector sees person/red/yellow). ``experiment_box`` is a real
#: object in the scenario but no shipped model can see it, so a test that invents
#: it would prove nothing about the live path.
#:
#: ``target_area`` is NOT injected here either — no detector can see it. It is
#: supplied as configuration (``ACTIVITY_TARGET_AREA``), exactly as the real
#: camera path does it, so these tests exercise that path rather than a fiction.
RESTING = {
    "person": PERSON,
    "red_box": RED_HOME,
    "yellow_box": YELLOW_HOME,
}

#: TARGET as a normalized config box, for a 1280x720 frame.
FRAME_W, FRAME_H = 1280, 720
TARGET_BOX = (
    TARGET[0] / FRAME_W,
    TARGET[1] / FRAME_H,
    (TARGET[0] + TARGET[2]) / FRAME_W,
    (TARGET[1] + TARGET[3]) / FRAME_H,
)


def _det(cls, x, y, w=SIZE, h=SIZE, conf=0.9) -> dict:
    return {
        "class_name": cls,
        "confidence": conf,
        "x1": x,
        "y1": y,
        "x2": x + w,
        "y2": y + h,
    }


def frame(**objects) -> list:
    """One frame: only the named objects are detected."""
    return [_det(cls, pos[0], pos[1]) for cls, pos in objects.items()]


def with_target_area(**objects) -> list:
    """One frame where a *detector* does see the target area.

    Not the shipped path (see ``TARGET_BOX``) — used to prove the source accepts
    a detected region just as happily as a configured one.
    """
    return [_det("target_area", *TARGET)] + frame(**objects)


def path(start, end, frames: int) -> list:
    out = []
    for i in range(frames):
        t = i / max(1, frames - 1)
        out.append((int(start[0] + (end[0] - start[0]) * t), int(start[1] + (end[1] - start[1]) * t)))
    return out


class FrameSource:
    """Detection-service stub replaying a scripted frame list, one frame per
    ``latest()`` call. The final frame repeats once the script is exhausted, so
    a static tail keeps polling (and proves nothing re-fires)."""

    def __init__(self, frames, enabled=True, status="ok", age_ms=0):
        self.frames = frames
        self.index = 0
        self.enabled = enabled
        self.status = status
        self.age_ms = age_ms
        self.polls = 0

    def latest(self) -> dict:
        self.polls += 1
        frame_dets = self.frames[min(self.index, len(self.frames) - 1)] if self.frames else []
        self.index += 1
        return {
            "enabled": self.enabled,
            "inferenceStatus": self.status,
            "lastInferenceMs": int(time.time() * 1000) - self.age_ms,
            "frameWidth": 1280,
            "frameHeight": 720,
            "detections": frame_dets,
        }

    def status(self) -> dict:
        return {"enabled": self.enabled, "inferenceStatus": self.status, "detector": "stub"}


def approach_frames(n: int = 5) -> list:
    return [frame(**RESTING) for _ in range(n)]


def open_frames() -> list:
    """OPEN_BOX is grounded on the first stored box moving (content jiggle).

    No shipped model can see the container or a lid, so the canonical step is
    credited by the red box sliding: past the tracker's 0.30x-diagonal motion
    threshold, so a real MOVED episode is produced.
    """
    return [
        frame(**{**RESTING, "red_box": (x, 430)})
        for x in range(420, 541, 20)
    ]


#: Where the red box ends up after the opening jiggle.
OPENED = {**RESTING, "red_box": (540, 430)}


def opened(n: int = 6) -> tuple[list, dict]:
    """Rest frames after the box has been jiggled open.

    The box has to come to rest before it is picked up again: the tracker
    reports one MOVED episode per *continuous* motion, so a box that never
    pauses would be a single episode and PICK_RED would have nothing new to
    consume. Real physics, not a convenience.
    """
    return [frame(**OPENED) for _ in range(n)], dict(OPENED)


def travel(state: dict, obj: str, end, frames: int = 12, still: int = 6) -> tuple[list, dict]:
    """Carry one object from where it is to ``end``, then let it rest there.

    Only ``obj`` moves — the others keep their positions, because an object
    that jumps back to its origin is a fresh movement episode and would be
    (correctly) reported as a new physical action.
    """
    out = []
    for pos in path(state[obj], end, frames):
        out.append(frame(**{**state, obj: pos}))
    state = {**state, obj: end}
    for _ in range(still):
        out.append(frame(**state))
    return out, state


def happy_frames() -> list:
    rest, state = opened()
    frames = approach_frames() + open_frames() + rest
    red, state = travel(state, "red_box", RED_TARGET)
    yellow, state = travel(state, "yellow_box", YELLOW_TARGET)
    return frames + red + yellow + [frame(**state) for _ in range(4)]


def wrong_object_frames() -> list:
    """Opens the box, lifts the *yellow* box first (wrong), then corrects."""
    rest, state = opened()
    frames = approach_frames() + open_frames() + rest
    lifted, state = travel(state, "yellow_box", (600, 300), frames=10)
    red, state = travel(state, "red_box", RED_TARGET)
    yellow, state = travel(state, "yellow_box", YELLOW_TARGET)
    return frames + lifted + red + yellow + [frame(**state) for _ in range(4)]


async def drive(session, perception, max_polls: int = 3000, until=None) -> list:
    events = []
    async for detection in perception.detections(max_idle_polls=max_polls):
        events.extend(session.on_detection(detection))
        if until is not None and until(session):
            break
    return events


def make(exp, source, session=None, **kw):
    session = session or ExperimentSession(exp)
    session.start()
    kw.setdefault("target_box", TARGET_BOX)
    perception = InteractionActivityPerception(
        exp,
        source,
        poll_ms=0,
        conf_threshold=0.5,
        confirm_polls=2,
        current_index=lambda: session.current_step_index,
        **kw,
    )
    return session, perception


# --------------------------------------------------------------- the procedure


def test_full_procedure_completes_on_real_motion() -> None:
    exp = load_active_experiment()
    session, perception = make(exp, FrameSource(happy_frames()))
    events = asyncio.run(drive(session, perception, until=lambda s: s.status == "COMPLETED"))
    kinds = [e.kind for e in events]
    assert session.status == "COMPLETED", kinds
    assert session.completed_step_ids == [s.id for s in exp.steps]
    assert "EXPERIMENT_COMPLETED" in kinds
    # A clean run produces no recourse at all.
    assert [k for k in kinds if k in ("WRONG_OBJECT", "WRONG_SEQUENCE", "OUT_OF_SEQUENCE")] == []


def test_every_step_is_grounded_in_motion_evidence() -> None:
    """Each PICK/PLACE step consumed exactly one physical episode."""
    exp = load_active_experiment()
    session, perception = make(exp, FrameSource(happy_frames()))
    events = asyncio.run(drive(session, perception, until=lambda s: s.status == "COMPLETED"))
    assert [e.activity for e in events if e.kind == "STEP_MATCHED"] == exp.activities
    facts = perception.status()["facts"]
    # red_box moves twice: once to open the box (OPEN_BOX), once to pick it up.
    assert facts["red_box"]["movedEpisodes"] == 2
    assert facts["red_box"]["placedEpisodes"] == 1
    assert facts["yellow_box"]["movedEpisodes"] == 1
    assert facts["yellow_box"]["placedEpisodes"] == 1
    # Nothing in the run claims a class no detector can emit.
    assert "experiment_box" not in facts


# ----------------------------------------------------- visibility is not action


def test_visible_objects_never_advance_a_pick() -> None:
    """Every expected object on screen, nothing ever moving: presence advances
    step 1, and no later step may fire on visibility alone."""
    exp = load_active_experiment()
    still = [frame(**RESTING) for _ in range(120)]
    session, perception = make(exp, FrameSource(still))
    asyncio.run(drive(session, perception, max_polls=600))
    assert session.completed_step_ids == ["step1"]
    assert session.current_step_index == 1


def test_settled_object_without_target_area_never_places() -> None:
    """A box that comes to rest is only PLACED when the destination is known.

    With neither a detected nor a configured target region there is nowhere to
    be inside, so PLACE must stay silent rather than assume the box was put
    down correctly. This is the *default* runtime state: no shipped detector
    sees the target, so the operator must configure it.
    """
    rest, state = opened()
    frames = approach_frames() + open_frames() + rest
    held, state = travel(state, "red_box", RED_TARGET, still=12)
    exp = load_active_experiment()
    session, perception = make(exp, FrameSource(frames + held), target_box=None)
    asyncio.run(drive(session, perception, max_polls=200))
    assert session.completed_step_ids == ["step1", "step2", "step3"]
    assert perception.status()["facts"]["red_box"]["placedEpisodes"] == 0
    status = perception.status()
    assert status["targetAreaSource"] == "none"
    assert status["placedGrounded"] is False
    # Polling status must not manufacture evidence for the missing target.
    assert "target_area" not in status["facts"]


def test_configured_target_area_grounds_placing_without_a_detector() -> None:
    """The real camera path: the destination is config, not perception."""
    rest, state = opened()
    frames = approach_frames() + open_frames() + rest
    held, state = travel(state, "red_box", RED_TARGET, still=12)
    exp = load_active_experiment()
    # No target_area detection anywhere in these frames.
    assert all(d["class_name"] != "target_area" for dets in held for d in dets)
    session, perception = make(exp, FrameSource(frames + held), target_box=TARGET_BOX)
    asyncio.run(drive(session, perception, max_polls=400))
    assert session.completed_step_ids[:5] == ["step1", "step2", "step3", "step4"]
    status = perception.status()
    assert status["targetAreaSource"] == "configured"
    assert status["placedGrounded"] is True
    assert status["facts"]["red_box"]["placedEpisodes"] >= 1


def test_a_detected_target_area_still_works() -> None:
    """A future real target detector keeps working; config only fills a gap."""
    rest, state = opened()
    frames = approach_frames() + open_frames() + rest
    held, state = travel(state, "red_box", RED_TARGET, still=12)
    detected = [
        with_target_area(**{d["class_name"]: (d["x1"], d["y1"]) for d in dets if d["class_name"] != "target_area"})
        for dets in held
    ]
    exp = load_active_experiment()
    session, perception = make(exp, FrameSource(frames + detected), target_box=None)
    asyncio.run(drive(session, perception, max_polls=400))
    assert session.completed_step_ids[:5] == ["step1", "step2", "step3", "step4"]
    assert perception.status()["targetAreaSource"] == "detector"


def test_an_out_of_range_configured_target_is_rejected() -> None:
    """A nonsense region must be ignored, not silently shrunk into a target."""
    import importlib
    import os

    from app.config import _target_area

    for raw in ("0.9,0.1,0.2,0.5", "0.1,0.1,0.2", "0.1,0.1,0.2,abc", "-1,0,0.5,0.5", ""):
        os.environ["ACTIVITY_TARGET_AREA"] = raw
        assert _target_area() is None, raw
    os.environ["ACTIVITY_TARGET_AREA"] = "0.5,0.5,0.75,0.8"
    assert _target_area() == (0.5, 0.5, 0.75, 0.8)
    os.environ.pop("ACTIVITY_TARGET_AREA", None)


# ------------------------------------------------------------- wrong behaviour


def test_wrong_object_is_reported_and_the_run_recovers() -> None:
    """Picking the yellow box while the red box is expected is WRONG_OBJECT,
    the yellow episode is spent, and the correct red pick still advances."""
    rest, state = opened()
    frames = approach_frames() + open_frames() + rest
    lifted, state = travel(state, "yellow_box", (600, 300), frames=10)
    red, state = travel(state, "red_box", RED_TARGET)
    yellow, state = travel(state, "yellow_box", YELLOW_TARGET)
    frames = frames + lifted + red + yellow + [frame(**state) for _ in range(4)]

    exp = load_active_experiment()
    session, perception = make(exp, FrameSource(frames))
    events = asyncio.run(drive(session, perception, until=lambda s: s.status == "COMPLETED"))
    kinds = [e.kind for e in events]
    assert "WRONG_OBJECT" in kinds
    assert session.status == "COMPLETED"
    assert session.completed_step_ids == [s.id for s in exp.steps]
    wrong = [e for e in events if e.kind == "WRONG_OBJECT"][0]
    assert wrong.activity == "PICK_YELLOW"
    assert wrong.expected == "PICK_RED"
    assert wrong.result == "WRONG_OBJECT"
    assert session.errors["wrongObject"] == 1
    assert session.errors["outOfSequence"] == 0


def test_one_episode_reports_once_and_holding_changes_nothing() -> None:
    exp = load_active_experiment()
    session, perception = make(exp, FrameSource(happy_frames()))
    events = asyncio.run(drive(session, perception, until=lambda s: s.status == "COMPLETED"))
    picks = [e for e in events if e.activity in ("PICK_RED", "PICK_YELLOW")]
    assert [e.activity for e in picks] == ["PICK_RED", "PICK_YELLOW"]
    # The scene keeps replaying its final (static) frame for hundreds of polls.
    before = session.completed_step_ids
    asyncio.run(drive(session, perception, max_polls=400))
    assert session.completed_step_ids == before


# ------------------------------------------------------------ grounded / honest


def test_stale_feed_never_advances() -> None:
    exp = load_active_experiment()
    source = FrameSource(happy_frames(), age_ms=60_000)  # camera stopped long ago
    session, perception = make(exp, source)
    asyncio.run(drive(session, perception, max_polls=300))
    assert session.completed_step_ids == []
    assert source.polls > 0


def test_disabled_or_errored_detector_never_advances() -> None:
    exp = load_active_experiment()
    for kwargs in ({"enabled": False}, {"status": "error"}):
        session, perception = make(exp, FrameSource(happy_frames(), **kwargs))
        asyncio.run(drive(session, perception, max_polls=200))
        assert session.completed_step_ids == [], kwargs


def test_steps_without_expected_events_never_fire() -> None:
    legacy = ExperimentDef(
        id="legacy",
        name="Legacy",
        steps=[StepDef(id="s1", activity="PICK_RED", label="Pick red")],  # no evidence contract
    )
    session, perception = make(legacy, FrameSource(happy_frames()))
    asyncio.run(drive(session, perception, max_polls=300))
    assert session.current_step_index == 0


def test_evidence_is_data_not_code() -> None:
    """A different procedure with its own evidence runs through the same seam."""
    exp = ExperimentDef(
        id="pair",
        name="Pair",
        objects=[{"id": "red_box", "role": "handled-object"}, {"id": "target_area", "role": "destination"}],
        steps=[
            StepDef(
                id="a", activity="LIFT", label="Lift the red box",
                expectedEvents=[{"event": "MOVED", "object": "red_box"}],
            ),
            StepDef(
                id="b", activity="SET_DOWN", label="Set down the red box",
                expectedEvents=[{"event": "PLACED", "object": "red_box"}],
            ),
        ],
    )
    frames = []
    for pos in path((300, 300), RED_TARGET, 12):
        frames.append([_det("target_area", *TARGET), _det("red_box", *pos)])
    for _ in range(6):
        frames.append([_det("target_area", *TARGET), _det("red_box", *RED_TARGET)])
    session, perception = make(exp, FrameSource(frames))
    events = asyncio.run(drive(session, perception, until=lambda s: s.status == "COMPLETED"))
    assert [e.activity for e in events if e.kind == "STEP_MATCHED"] == ["LIFT", "SET_DOWN"]


def test_tracker_prefixes_derive_from_the_experiment_objects() -> None:
    assert tracker_prefixes(load_active_experiment()) == {
        "experiment_box": "EXPERIMENT",
        "red_box": "RED",
        "yellow_box": "YELLOW",
    }
    bare = ExperimentDef(id="b", name="b", steps=[])
    assert tracker_prefixes(bare) == {"red_box": "RED", "yellow_box": "YELLOW"}  # demo fallback


def test_reset_clears_accumulated_evidence() -> None:
    exp = load_active_experiment()
    session, perception = make(exp, FrameSource(happy_frames()))
    asyncio.run(drive(session, perception, until=lambda s: s.status == "COMPLETED"))
    assert perception.status()["facts"]["red_box"]["movedEpisodes"] == 2
    perception.reset()
    assert perception.status()["facts"] == {}
    assert perception.status()["events"] == []


# ------------------------------------------------------------ regression guards


def test_a_cumulative_step_is_never_re_offered() -> None:
    """A refused cumulative (terminal) step must not be emitted over and over.

    COMPLETE's rules are all ``fresh: false``, so there is no episode to spend
    and nothing else would stop the source re-offering it. The state machine
    refuses it (out of sequence), the pointer never moves, and the old code
    emitted COMPLETE on every poll forever - a busy loop that spams the log and
    hides the real activity.
    """
    exp = load_active_experiment()
    session, perception = make(exp, FrameSource(happy_frames()))
    emitted = asyncio.run(drive(session, perception, max_polls=200))
    activities = [e.activity for e in emitted if e.kind == "STEP_MATCHED"]
    assert activities.count("COMPLETE") == 1
    # The run finished, and nothing kept firing afterwards.
    assert session.status == "COMPLETED"
    assert activities == exp.activities


def test_consuming_one_step_does_not_starve_the_next() -> None:
    """Evidence for a later step survives an earlier step's confirmation delay.

    OPEN_BOX waits ``confirm_polls`` frames before firing, by which time the
    red box may already have moved again for PICK_RED. Consuming "everything
    seen so far" instead of one episode silently skipped PICK_RED and let the
    run report PLACE_RED as the very next action.
    """
    exp = load_active_experiment()
    session, perception = make(exp, FrameSource(happy_frames()))
    emitted = asyncio.run(drive(session, perception, until=lambda s: s.status == "COMPLETED"))
    matched = [e.activity for e in emitted if e.kind == "STEP_MATCHED"]
    assert matched == exp.activities
    assert [k for k in (e.kind for e in emitted) if k in ("WRONG_OBJECT", "WRONG_SEQUENCE", "OUT_OF_SEQUENCE")] == []

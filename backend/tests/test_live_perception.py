"""Tests for the camera-grounded ``LiveActivityPerception`` (ACTIVITY_BACKEND=live):

1. Unit-level: a stub ``latest()`` source drives trials over the canonical
   experiment; only fully-visible expectedObjects emit, missing/absent
   required objects block, stale or disabled inference blocks, emission is
   edge-triggered (a step fires at most once), and blank expectedObjects
   never fire.
2. End-to-end over HTTP: empty scene advances nothing; a visible person
   advances exactly step 1.
"""

import asyncio
import time
from typing import List, Optional

from fastapi.testclient import TestClient

from app import config as app_config
from app.activity_perception import LiveActivityPerception
from app.main import create_app
from app.schemas import ExperimentDef, StepDef
from app.state_machine import ExperimentSession

PERSON = {"class_name": "person", "confidence": 0.95}
EXPERIMENT_BOX = {"class_name": "experiment_box", "confidence": 0.95}
RED_BOX = {"class_name": "red_box", "confidence": 0.95}
TARGET_AREA = {"class_name": "target_area", "confidence": 0.95}


class SceneSource:
    """Detection-service stub with a ``latest()``/``status()`` contract and
    controllable scenes: list of ``(max_calls, detections)`` windows, ordered
    by ascending ``max_calls``. After the last window the final scene persists.
    """

    def __init__(self, windows: List[tuple[int, list]]):
        self.windows = windows
        self.calls = 0
        self.forced: Optional[dict] = None

    def latest(self) -> dict:
        self.calls += 1
        if self.forced is not None:
            return self.forced
        scene = self.windows[-1][1]
        for cap, dets in self.windows:
            if self.calls <= cap:
                scene = dets
                break
        return {
            "enabled": True,
            "inferenceStatus": "ok",
            "lastInferenceMs": int(time.time() * 1000),
            "detections": scene,
        }

    def status(self) -> dict:
        return {"enabled": True, "inferenceStatus": "ok", "detector": "stub"}


def make_exp() -> ExperimentDef:
    return ExperimentDef(
        id="trial",
        name="Trial",
        steps=[
            StepDef(id="s1", activity="APPROACH", label="Approach", expectedObjects=["person"]),
            StepDef(id="s2", activity="OPEN_BOX", label="Open", expectedObjects=["experiment_box"]),
            StepDef(id="s3", activity="PICK_RED", label="Pick red", expectedObjects=["red_box"]),
            StepDef(id="s4", activity="PLACE_RED", label="Place red", expectedObjects=["red_box", "target_area"]),
        ],
    )


def make_perception(exp: ExperimentDef, source: SceneSource, **kw) -> LiveActivityPerception:
    session = ExperimentSession(exp)
    session.start()
    perception = LiveActivityPerception(
        exp,
        source,
        poll_ms=1,
        current_index=lambda: session.current_step_index,
        **kw,
    )
    return session, perception


async def drive(
    session: ExperimentSession,
    perception: LiveActivityPerception,
    max_polls: int = 2000,
    until=None,
) -> list:
    """Run the perception loop against ``session`` for at most ``max_polls``
    idle polls (or until ``until(session)``), returning the classification
    events."""
    events = []
    async for detection in perception.detections(max_idle_polls=max_polls):
        events.extend(session.on_detection(detection))
        if until is not None and until(session):
            break
    return events


# ---------------------------------------------------------------- unit level


def test_empty_global_scene_never_advances() -> None:
    exp = make_exp()
    session, perception = make_perception(exp, SceneSource([(10_000, [])]))
    events = asyncio.run(drive(session, perception, max_polls=600))
    assert events == []
    assert session.current_step_index == 0
    assert session.completed_step_ids == []


def test_visible_person_advances_exactly_step_one() -> None:
    exp = make_exp()
    session, perception = make_perception(exp, SceneSource([(10_000, [PERSON])]))
    events = asyncio.run(drive(session, perception, until=lambda s: s.current_step_index >= 1))
    assert [e.kind for e in events] == ["STEP_MATCHED"]
    assert session.completed_step_ids == ["s1"]
    # Holding the person in view must not repeat or chain into OPEN_BOX (no
    # experiment_box in view).
    events_hold = asyncio.run(drive(session, perception, max_polls=400))
    assert events_hold == []
    assert session.current_step_index == 1


def test_missing_required_object_blocks_open_box() -> None:
    exp = make_exp()
    session, perception = make_perception(exp, SceneSource([(10_000, [PERSON])]))
    asyncio.run(drive(session, perception, max_polls=500))
    assert session.current_step_index == 1  # OPEN_BOX never fires


def test_full_sequence_advances_on_visible_objects() -> None:
    exp = make_exp()
    session, perception = make_perception(
        exp,
        SceneSource([(5, [PERSON]), (10, [EXPERIMENT_BOX]), (15, [RED_BOX]), (10_000, [RED_BOX, TARGET_AREA])]),
    )
    events = asyncio.run(drive(session, perception, until=lambda s: s.current_step_index >= 4))
    assert [e.kind for e in events] == [
        "STEP_MATCHED",
        "STEP_MATCHED",
        "STEP_MATCHED",
        "STEP_MATCHED",
        "EXPERIMENT_COMPLETED",
        "RECORDING_STOPPED",
    ]
    assert session.completed_step_ids == ["s1", "s2", "s3", "s4"]
    assert session.current_step_index == 4


def test_confidence_below_threshold_blocks() -> None:
    exp = make_exp()
    session, perception = make_perception(
        exp,
        SceneSource([(10_000, [{"class_name": "person", "confidence": 0.42}])]),
    )
    asyncio.run(drive(session, perception, max_polls=300))
    assert session.current_step_index == 0


def test_partial_required_set_blocks_place_red() -> None:
    exp = make_exp()
    session, perception = make_perception(
        exp,
        SceneSource([(5, [PERSON]), (10, [EXPERIMENT_BOX]), (10_000, [RED_BOX])]),
    )
    asyncio.run(drive(session, perception, max_polls=1500))
    # Sequence reaches s4 with red_box visible but target_area never present:
    # PLACE_RED (s4) must not fire — its expectedObjects are all-or-nothing.
    assert session.completed_step_ids == ["s1", "s2", "s3"]
    assert session.current_step_index == 3


def test_edge_triggered_same_object_advances_both_steps() -> None:
    exp = ExperimentDef(
        id="pair",
        name="Pair",
        steps=[
            StepDef(id="a", activity="PICK_RED", label="Pick", expectedObjects=["red_box"], terminal=False),
            StepDef(id="b", activity="PLACE_RED", label="Place", expectedObjects=["red_box"], terminal=True),
        ],
    )
    session, perception = make_perception(exp, SceneSource([(10_000, [RED_BOX])]))
    events = asyncio.run(drive(session, perception, until=lambda s: s.status == "COMPLETED"))
    assert [e.kind for e in events] == ["STEP_MATCHED", "STEP_MATCHED", "EXPERIMENT_COMPLETED", "RECORDING_STOPPED"]
    assert session.completed_step_ids == ["a", "b"]


def test_stale_inference_blocks() -> None:
    exp = make_exp()
    source = SceneSource([(10_000, [PERSON])])
    source.forced = {
        "enabled": True,
        "inferenceStatus": "ok",
        "lastInferenceMs": int(time.time() * 1000) - 60_000,  # camera stopped long ago
        "detections": [PERSON],
    }
    session, perception = make_perception(exp, source, stale_after_ms=5000)
    asyncio.run(drive(session, perception, max_polls=300))
    assert session.current_step_index == 0


def test_disabled_or_idle_inference_blocks() -> None:
    exp = make_exp()
    source = SceneSource([(10_000, [PERSON])])
    source.forced = {"enabled": True, "inferenceStatus": "idle", "lastInferenceMs": None, "detections": [PERSON]}
    session, perception = make_perception(exp, source)
    asyncio.run(drive(session, perception, max_polls=300))
    assert session.current_step_index == 0


def test_blank_expected_objects_never_fire() -> None:
    legacy = ExperimentDef(
        id="legacy",
        name="Legacy",
        steps=[StepDef(id="s1", activity="APPROACH", label="Approach")],  # no expectedObjects
    )
    session, perception = make_perception(legacy, SceneSource([(10_000, [PERSON])]))
    asyncio.run(drive(session, perception, max_polls=300))
    assert session.current_step_index == 0


def test_reset_clears_fired_state() -> None:
    exp = make_exp()
    session, perception = make_perception(exp, SceneSource([(10_000, [PERSON])]))
    asyncio.run(drive(session, perception, until=lambda s: s.current_step_index >= 1))
    assert perception._fired == {"s1"}
    perception.reset()
    assert perception._fired == set()


# ----------------------------------------------------------------- end to end


def test_live_e2e_empty_scene_blocks(monkeypatch) -> None:
    monkeypatch.setattr(app_config, "ACTIVITY_POLL_MS", 5)
    with TestClient(
        create_app(activity_backend="live", detection_service=SceneSource([(10_000, [])]))
    ) as client:
        assert client.get("/api/health").json()["source"] == "live"
        state = client.post("/api/experiment/start").json()
        assert state["status"] == "RUNNING"
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            state = client.get("/api/experiment/status").json()
            assert state["currentStepIndex"] == 0
            time.sleep(0.02)
        bodies = client.get("/api/logs").json()["events"]
        assert [e["kind"] for e in bodies] == ["EXPERIMENT_STARTED", "RECORDING_STARTED"]


def test_live_e2e_person_advances_step_one(monkeypatch) -> None:
    monkeypatch.setattr(app_config, "ACTIVITY_POLL_MS", 5)
    source = SceneSource([(10_000, [PERSON])])
    with TestClient(create_app(activity_backend="live", detection_service=source)) as client:
        assert client.get("/api/health").json()["source"] == "live"
        client.post("/api/experiment/start")
        deadline = time.monotonic() + 5.0
        state = None
        while time.monotonic() < deadline:
            state = client.get("/api/experiment/status").json()
            if state["currentStepIndex"] == 1:
                break
            time.sleep(0.02)
        assert state is not None and state["currentStepIndex"] == 1
        assert state["completedStepIds"] == ["step1"]
        assert state["lastClassification"]["kind"] == "STEP_MATCHED"
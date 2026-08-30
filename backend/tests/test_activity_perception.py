"""Tests for the Phase 5C runtime integration:

1. The canonical experiment/experiment.json becomes the runtime default (the
   single source every runtime module consumes).
2. The pluggable activity-perception stage (live is the default; mock and sim
   opted in explicitly) feeds the state machine through the same REST +
   WebSocket path the simulator used, and the scripted sim feed still works
   when a sim_script is injected.
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import experiment as experiment_module
from app.activity_perception import (
    UNKNOWN_ACTIVITY,
    MockActivityPerception,
    standard_plan,
)
from app.experiment import load_active_experiment
from app.main import create_app

BACKEND = Path(__file__).resolve().parent.parent
BOX_SEQUENCE = BACKEND / "experiments" / "box_sequence.json"

CANONICAL_ACTIVITIES = [
    "APPROACH",
    "OPEN_BOX",
    "PICK_RED",
    "PLACE_RED",
    "PICK_YELLOW",
    "PLACE_YELLOW",
    "COMPLETE",
]


def make_mock_client(monkeypatch) -> TestClient:
    """App wiring exactly like production: no sim_script, mock backend, but a
    fast polling interval so the run finishes quickly."""
    monkeypatch.setattr(app_config, "ACTIVITY_POLL_MS", 5)
    return TestClient(create_app(activity_backend="mock"))


def wait_until(client: TestClient, predicate, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get("/api/experiment/status").json()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise AssertionError("condition not met within timeout")


# ---------------------------------------------------------------- experiment


def test_canonical_experiment_is_runtime_default() -> None:
    exp = load_active_experiment()
    assert exp.id == "bas-box-handling-01"
    assert exp.activities == CANONICAL_ACTIVITIES
    assert [s.activity for s in exp.steps] == CANONICAL_ACTIVITIES
    assert exp.steps[-1].terminal is True
    assert exp.disclaimer
    assert exp.objects  # canonical object/classId table survives the schema


def test_experiment_file_env_override(monkeypatch) -> None:
    monkeypatch.setattr(experiment_module, "EXPERIMENT_FILE", str(BOX_SEQUENCE))
    assert load_active_experiment().id == "bas-box-sequence-01"


# ------------------------------------------------------------- standard plan


def test_standard_plan_follows_canonical_steps() -> None:
    exp = load_active_experiment()
    plan = standard_plan(exp, poll_ms=100)
    correct = [item["activity"] for item in plan if item["confidence"] == 0.95]
    assert correct == CANONICAL_ACTIVITIES
    assert plan[-1]["activity"] == "COMPLETE"
    assert plan[-1]["confidence"] == 0.95
    assert len(plan) == 2 * len(exp.steps) - 1  # one mistake per completed step


def test_standard_plan_is_deterministic() -> None:
    exp = load_active_experiment()
    assert standard_plan(exp, poll_ms=100) == standard_plan(exp, poll_ms=100)


def test_standard_plan_covers_every_outcome() -> None:
    plan = standard_plan(load_active_experiment(), poll_ms=100)
    mistake_conf = [item["confidence"] for item in plan if item["confidence"] != 0.95]
    assert 0.9 in mistake_conf      # out-of-sequence later step
    assert 0.97 in mistake_conf     # repeated earlier step
    assert 0.42 in mistake_conf     # low-confidence expected step
    assert UNKNOWN_ACTIVITY in [i["activity"] for i in plan]


# ------------------------------------------------------- mock perception feed


def test_mock_perception_yields_plan() -> None:
    exp = load_active_experiment()
    plan = standard_plan(exp, poll_ms=1)
    feed = MockActivityPerception(exp, poll_ms=1)

    import asyncio

    async def drain():
        return [d.activity async for d in feed.detections()]

    assert asyncio.run(drain()) == [item["activity"] for item in plan]


# --------------------------------------------------------------- end to end


def test_canonical_mock_run_e2e(monkeypatch) -> None:
    with make_mock_client(monkeypatch) as client:
        assert client.get("/api/health").json()["source"] == "mock-activity"

        body = client.get("/api/experiment").json()
        assert body["experiment"]["id"] == "bas-box-handling-01"
        assert len(body["experiment"]["steps"]) == 7
        assert body["state"]["status"] == "IDLE"

        state = client.post("/api/experiment/start").json()
        assert state["status"] == "RUNNING"

        final = wait_until(client, lambda s: s["status"] == "COMPLETED")
        assert final["recording"] is False
        assert [s["activity"] for s in final["experiment"]["steps"]] == CANONICAL_ACTIVITIES
        # Every classification outcome fires exactly once per planted mistake.
        assert final["errors"] == {
            "outOfSequence": 2,
            "skipped": 2,
            "repeated": 2,
            "unknown": 1,
            "lowConfidence": 1,
        }
        logs = client.get("/api/logs").json()["events"]
        kinds = [e["kind"] for e in logs]
        assert kinds.count("STEP_MATCHED") == 7
        assert kinds.count("OUT_OF_SEQUENCE") == 2
        assert kinds.count("SKIPPED_STEP") == 2
        assert kinds.count("REPEATED_STEP") == 2
        assert kinds.count("UNKNOWN_ACTIVITY") == 1
        assert kinds.count("LOW_CONFIDENCE") == 1


def test_sim_backend_still_runs_with_injected_script(monkeypatch) -> None:
    # A provided sim_script opts into the scripted feed regardless of config
    # (the production default is mock; the script path is test/back-compat).
    monkeypatch.setattr(app_config, "ACTIVITY_POLL_MS", 5)
    script = [{"delay_ms": 5, "activity": "APPROACH", "confidence": 0.96}]
    exp = load_active_experiment()
    with TestClient(create_app(experiment=exp, sim_script=script)) as client:
        assert client.get("/api/health").json()["source"] == "simulated"
        client.post("/api/experiment/start")
        final = wait_until(client, lambda s: s["status"] == "RUNNING" and s["currentStepIndex"] == 1)
        assert final["completedStepIds"] == ["step1"]
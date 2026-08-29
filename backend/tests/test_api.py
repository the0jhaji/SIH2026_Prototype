"""REST + WebSocket integration tests using the FastAPI TestClient."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.experiment import load_experiment
from app.main import create_app

EXPERIMENTS = Path(__file__).resolve().parent.parent / "experiments"

FAST_SCRIPT = [
    {"delay_ms": 10, "activity": "PICK_MAIN_BOX", "confidence": 0.96},
    {"delay_ms": 10, "activity": "OPEN_EXPERIMENT_BOX", "confidence": 0.91},
    {"delay_ms": 10, "activity": "PICK_RED_BOX", "confidence": 0.93},
    {"delay_ms": 10, "activity": "PLACE_RED_BOX", "confidence": 0.9},
    {"delay_ms": 10, "activity": "PICK_YELLOW_BOX", "confidence": 0.95},
    {"delay_ms": 10, "activity": "PLACE_YELLOW_BOX", "confidence": 0.94},
]

EXP = load_experiment(EXPERIMENTS / "box_sequence.json")


def make_client() -> TestClient:
    return TestClient(create_app(experiment=EXP, sim_script=FAST_SCRIPT))


def wait_until(client: TestClient, predicate, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get("/api/experiment/status").json()
        if predicate(state):
            return state
        time.sleep(0.02)
    raise AssertionError("condition not met within timeout")


def test_health() -> None:
    with make_client() as client:
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["source"] == "simulated"
        assert body["experiment_id"] == EXP.id


def test_experiment_definition_served() -> None:
    with make_client() as client:
        body = client.get("/api/experiment").json()
        assert body["experiment"]["id"] == EXP.id
        assert len(body["experiment"]["steps"]) == 6
        assert body["state"]["status"] == "IDLE"


def test_full_simulation_run() -> None:
    with make_client() as client:
        state = client.post("/api/experiment/start").json()
        assert state["status"] == "RUNNING"
        assert state["recording"] is True

        final = wait_until(client, lambda s: s["status"] == "COMPLETED")
        assert len(final["completedStepIds"]) == 6
        assert final["recording"] is False
        assert final["errors"] == {"outOfSequence": 0, "skipped": 0, "repeated": 0,
                                   "unknown": 0, "lowConfidence": 0}

        logs = client.get("/api/logs").json()["events"]
        kinds = [e["kind"] for e in logs]
        assert kinds.count("STEP_MATCHED") == 6
        assert "EXPERIMENT_COMPLETED" in kinds


def test_log_sequence_ordered() -> None:
    with make_client() as client:
        client.post("/api/experiment/start")
        wait_until(client, lambda s: s["status"] == "COMPLETED")
        logs = client.get("/api/logs").json()["events"]
        seqs = [e["seq"] for e in logs]
        assert seqs == sorted(seqs)


def test_error_events_reported_via_api() -> None:
    script = [
        {"delay_ms": 10, "activity": "PICK_MAIN_BOX", "confidence": 0.96},
        {"delay_ms": 10, "activity": "PICK_RED_BOX", "confidence": 0.85},
        {"delay_ms": 10, "activity": "PICK_MAIN_BOX", "confidence": 0.9},
        {"delay_ms": 10, "activity": "STIR_FLUID", "confidence": 0.7},
    ]
    with TestClient(create_app(experiment=EXP, sim_script=script)) as client:
        client.post("/api/experiment/start")
        state = wait_until(client, lambda s: s["errors"]["unknown"] == 1)
        assert state["errors"]["outOfSequence"] == 1
        assert state["errors"]["skipped"] == 1
        assert state["errors"]["repeated"] == 1
        logs = [e["kind"] for e in client.get("/api/logs").json()["events"]]
        assert "OUT_OF_SEQUENCE" in logs
        assert "SKIPPED_STEP" in logs
        assert "REPEATED_STEP" in logs
        assert "UNKNOWN_ACTIVITY" in logs


def test_stop_experiment() -> None:
    with make_client() as client:
        client.post("/api/experiment/start")
        wait_until(client, lambda s: s["status"] == "RUNNING")
        state = client.post("/api/experiment/stop").json()
        assert state["status"] == "STOPPED"
        logs = client.get("/api/logs").json()["events"]
        assert logs[-2]["kind"] == "EXPERIMENT_STOPPED"
        assert logs[-1]["kind"] == "RECORDING_STOPPED"


def test_websocket_handshake_and_ping() -> None:
    with make_client() as client:
        with client.websocket_connect("/ws") as ws:
            snapshot = ws.receive_json()
            assert snapshot["type"] == "state"
            assert snapshot["data"]["status"] == "IDLE"
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
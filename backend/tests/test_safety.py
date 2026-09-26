"""Astronaut safety system tests (Phase 5 / hazard + emergency).

Covers the core contract: temporal hazard confirmation, microgravity risk
scoring, astronaut status / emergency candidates, alerts (dedup / ack /
resolve), incidents + evidence, Earth-escalation packaging (local only), and
the "no silent mock fallback" rule when detection errors out.

Runs on a stub/injected detection feed or the mock detector — never a physical
camera or real model weights.
"""

import asyncio
import json
import time
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from camera import CameraSettings
from app import config
from app.experiment import load_experiment
from app.main import create_app
from app.safety.alert_manager import AlertManager
from app.safety.emergency import EmergencyManager, EmergencySignal
from app.safety.hazard_engine import HazardEngine, risk_level_for
from app.safety.incidents import IncidentLog
from app.safety.monitor import SafetyMonitor
from app.safety.transports import LocalMissionControlTransport

EXPERIMENTS = Path(__file__).resolve().parent.parent / "experiments"
EXP = load_experiment(EXPERIMENTS / "box_sequence.json")

FAST_SCRIPT = [{"delay_ms": 5, "activity": "PICK_MAIN_BOX", "confidence": 0.96}]

MOCK_SETTINGS = CameraSettings(mock=True, width=320, height=240, fps=120)

#: Safety services built by these tests. They poll a detection thread for the
#: whole pytest session otherwise, which starves later suites and leaks work.
_STARTED: list = []


@pytest.fixture(autouse=True)
def _stop_started_safety_services():
    yield
    for svc in _STARTED:
        asyncio.run(svc.stop())
    _STARTED.clear()


from ai.detection.detector import create_detector  # noqa: E402

PERSON = {"class_name": "person", "confidence": 0.95, "x1": 150, "y1": 20, "x2": 208, "y2": 100}
TOOL_FAR = {"class_name": "floating_tool", "confidence": 0.92, "x1": 240, "y1": 160, "x2": 270, "y2": 190}
TOOL_NEAR = {"class_name": "floating_tool", "confidence": 0.92, "x1": 140, "y1": 15, "x2": 170, "y2": 45}
UNSECURED_FAR = {"class_name": "unsecured_object", "confidence": 0.93, "x1": 245, "y1": 150, "x2": 275, "y2": 180}
UNSECURED_NEAR = {"class_name": "unsecured_object", "confidence": 0.93, "x1": 140, "y1": 15, "x2": 172, "y2": 45}
SHARP_NEAR = {"class_name": "sharp_object", "confidence": 0.9, "x1": 138, "y1": 16, "x2": 166, "y2": 44}
MYSTERY = {"class_name": "chicken_suit", "confidence": 0.8, "x1": 10, "y1": 10, "x2": 50, "y2": 50}


def payload(dets, *, enabled=True, last_inf=None, status="ok", w=320, h=240) -> dict:
    now = int(time.time() * 1000)
    return {
        "enabled": enabled,
        "frameWidth": w,
        "frameHeight": h,
        "detections": list(dets),
        "lastInferenceMs": last_inf if last_inf is not None else now,
        "inferenceMs": 5,
        "inferenceStatus": status,
        "error": None,
    }


class StubDetection:
    """Injectable detection service stand-in: tests control the feed directly."""

    def __init__(self, init_payload=None) -> None:
        self._payload = payload([]) if init_payload is None else init_payload

    def set(self, new_payload: dict) -> None:
        self._payload = new_payload

    def latest(self) -> dict:
        return dict(self._payload)

    def status(self) -> dict:
        return {
            "enabled": bool(self._payload.get("enabled")),
            "detector": "stub",
            "modelLoaded": True,
            "modelPath": "@test/stub",
            "classes": ["person", "floating_tool", "unsecured_object", "sharp_object"],
            "inferenceStatus": self._payload.get("inferenceStatus", "ok"),
            "error": None,
        }


def build_safety_client(
    tmp_path: Path,
    stub: StubDetection,
    *,
    poll_ms: int = 10,
    persist: int = 2,
    resolve: int = 2,
    absent_frames: int = 2,
    static_frames: int = 1_000_000,  # tests move the astronaut; immobility tests opt in
    autostart: bool = True,
    transport=None,
) -> tuple[TestClient, IncidentLog, LocalMissionControlTransport]:
    incidents = IncidentLog(root=tmp_path / "incidents", model_version="test")
    transport = transport or LocalMissionControlTransport()
    app = create_app(
        experiment=EXP,
        sim_script=FAST_SCRIPT,
        camera=MOCK_SETTINGS,
        detection_service=stub,
        safety_autostart=autostart,
        safety_poll_ms=poll_ms,
        safety_hazard_engine=HazardEngine(
            environment_mode="microgravity",
            persist_frames=persist,
            resolve_frames=resolve,
            stale_after_ms=60_000,
        ),
        safety_emergency=EmergencyManager(backend="rules", absent_frames=absent_frames, static_frames=static_frames),
        safety_alerts=AlertManager(cooldown_ms=600_000),
        safety_incidents=incidents,
        safety_transport=transport,
    )
    client = TestClient(app)
    _STARTED.append(app.state.safety_service)
    return client, incidents, transport


def wait_status(client: TestClient, predicate, timeout: float = 6.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/safety/status").json()
        if predicate(body):
            return body
        time.sleep(0.015)
    raise AssertionError("condition not met within timeout")


def wait_snapshot(client: TestClient, predicate, timeout: float = 6.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/safety/snapshot").json()
        if predicate(body):
            return body
        time.sleep(0.015)
    raise AssertionError("snapshot condition not met within timeout")


def wait_ticks(client: TestClient, n: int, timeout: float = 6.0) -> dict:
    return wait_status(client, lambda s: s["tick"] >= n, timeout)


# ------------------------------------------------------------------ scoring


def test_safe_objects_never_raise_hazard_or_alert(tmp_path) -> None:
    stub = StubDetection(payload([PERSON]))
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(3):
            stub.set(payload([PERSON, {"class_name": "red_box", "confidence": 0.91, "x1": 40, "y1": 150, "x2": 90, "y2": 200}]))
            time.sleep(0.03)
        body = wait_snapshot(client, lambda s: s["monitoring"] is True)
        assert body["overall_risk_level"] == "SAFE"
        assert all(not a["hazard"] for a in body["assessments"])
        assert body["astronaut_in_view"] is True
        alerts = client.get("/api/safety/alerts").json()["active"]
        assert alerts == []
        assert incidents.incidents() == []
        status = client.get("/api/safety/status").json()
        assert status["mission_state"] == "NORMAL"


def test_known_hazard_far_from_astronaut_is_confirmed_warning(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, TOOL_FAR]))
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(3):
            stub.set(payload([PERSON, TOOL_FAR]))
            time.sleep(0.03)
        snap = wait_snapshot(
            client,
            lambda s: any(a["object"] == "floating_tool" and a["confirmed"] for a in s["assessments"]),
        )
        tool = next(a for a in snap["assessments"] if a["object"] == "floating_tool")
        assert tool["hazard"] is True
        assert tool["risk_level"] == "WARNING"
        assert tool["near_astronaut"] is False
        assert tool["risk_score"] < 0.8
        # A WARNING far from the astronaut is an alert but not an incident.
        alerts = client.get("/api/safety/alerts").json()["active"]
        assert len(alerts) == 1 and alerts[0]["level"] == "WARNING"
        assert incidents.incidents() == []


def test_hazard_near_astronaut_escalates_to_critical(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, TOOL_NEAR]))
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(3):
            stub.set(payload([PERSON, TOOL_NEAR]))
            time.sleep(0.03)
        snap = wait_snapshot(
            client,
            lambda s: any(a["object"] == "floating_tool" and a["confirmed"] for a in s["assessments"]),
        )
        tool = next(a for a in snap["assessments"] if a["object"] == "floating_tool")
        assert tool["risk_level"] == "CRITICAL"
        assert tool["near_astronaut"] is True
        assert snap["mission_state"] == "CRITICAL"


def test_microgravity_elevates_free_floating_risk(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, TOOL_FAR]))
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(3):
            stub.set(payload([PERSON, TOOL_FAR]))
            time.sleep(0.03)
        micro = wait_snapshot(client, lambda s: any(a["object"] == "floating_tool" for a in s["assessments"]))
        micro_score = next(a for a in micro["assessments"] if a["object"] == "floating_tool")["risk_score"]

    app = create_app(
        experiment=EXP,
        sim_script=FAST_SCRIPT,
        camera=MOCK_SETTINGS,
        detection_service=StubDetection(payload([PERSON, TOOL_FAR])),
        safety_autostart=True,
        safety_poll_ms=10,
        safety_hazard_engine=HazardEngine(
            environment_mode="planetary", persist_frames=1, resolve_frames=1, stale_after_ms=60_000
        ),
        safety_emergency=EmergencyManager(backend="none"),
        safety_alerts=AlertManager(),
        safety_incidents=IncidentLog(root=tmp_path / "planetary", model_version="test"),
        safety_transport=LocalMissionControlTransport(),
    )
    with TestClient(app) as client:
        for _ in range(3):
            time.sleep(0.03)
        planetary = wait_snapshot(
            client,
            lambda s: any(a["object"] == "floating_tool" and a["confirmed"] for a in s["assessments"]),
        )
        planetary_score = next(a for a in planetary["assessments"] if a["object"] == "floating_tool")["risk_score"]
        assert micro_score > planetary_score > 0.0


def test_one_frame_blip_never_raises_alert_or_incident(tmp_path) -> None:
    # Temporal gate at the engine level: a single frame can never exceed CAUTION.
    engine = HazardEngine(environment_mode="microgravity", persist_frames=2, resolve_frames=2, stale_after_ms=60_000)
    first = engine.assess(payload([PERSON, SHARP_NEAR]))
    tool = next(a for a in first.assessments if a.object == "sharp_object")
    assert tool.confirmed is False
    assert tool.risk_level == "CAUTION"
    assert tool.risk_score <= 0.54

    # A genuine one-frame blip on the wire must never produce alert/incident.
    stub = StubDetection(payload([PERSON]))
    client, incidents, _transport = build_safety_client(tmp_path, stub, poll_ms=100)
    with client:
        wait_ticks(client, 3)
        stub.set(payload([PERSON, SHARP_NEAR]))
        time.sleep(0.05)  # shorter than one loop tick -> exactly one blip frame
        stub.set(payload([PERSON]))
        wait_ticks(client, 8)
        snap = client.get("/api/safety/snapshot").json()
        assert snap["mission_state"] not in {"CRITICAL", "EMERGENCY"}
        assert client.get("/api/safety/alerts").json()["active"] == []
        assert incidents.incidents() == []


def test_persistent_hazard_then_clean_frames_resolves(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, UNSECURED_FAR]))
    client, incidents, _transport = build_safety_client(tmp_path, stub, resolve=2)
    with client:
        for _ in range(3):
            stub.set(payload([PERSON, UNSECURED_FAR]))
            time.sleep(0.03)
        wait_snapshot(client, lambda s: s["mission_state"] == "WARNING")
        # Hazard clears -> RESOLVED after resolve_cycles clean fresh frames.
        for _ in range(4):
            stub.set(payload([PERSON]))
            time.sleep(0.03)
        snap = wait_snapshot(client, lambda s: s["mission_state"] == "NORMAL")
        assert snap["overall_risk_level"] == "SAFE"


# ------------------------------------------------------------ alert lifecycle


def test_alert_raised_once_deduped_while_active(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, UNSECURED_NEAR]))
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(5):
            stub.set(payload([PERSON, UNSECURED_NEAR]))
            time.sleep(0.03)
        wait_snapshot(client, lambda s: s["mission_state"] == "CRITICAL")
        alert_body = client.get("/api/safety/alerts").json()
        assert len(alert_body["active"]) == 1
        events = client.get("/api/safety/events").json()["events"]
        raised = [e for e in events if e["kind"] == "ALERT_RAISED"]
        assert len(raised) == 1


def test_alert_resolution_and_dedupe_cooldown(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, UNSECURED_NEAR]))
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(3):
            stub.set(payload([PERSON, UNSECURED_NEAR]))
            time.sleep(0.03)
        wait_snapshot(client, lambda s: s["mission_state"] == "CRITICAL")
        active = client.get("/api/safety/alerts").json()["active"]
        assert len(active) == 1
        alert_id = active[0]["id"]

        # Hazard clears -> alert auto-resolves.
        for _ in range(4):
            stub.set(payload([PERSON]))
            time.sleep(0.03)
        wait_status(client, lambda s: s["alerts_active"] == 0)
        alerts = client.get("/api/safety/alerts").json()
        resolved = [a for a in alerts["all"] if a["id"] == alert_id]
        assert resolved and resolved[0]["resolved"] is True

        # Re-appearing within the cooldown window must NOT raise a fresh alert.
        for _ in range(3):
            stub.set(payload([PERSON, UNSECURED_NEAR]))
            time.sleep(0.03)
        wait_snapshot(client, lambda s: s["mission_state"] == "CRITICAL")
        assert client.get("/api/safety/alerts").json()["active"] == []


def test_alert_acknowledgement(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, UNSECURED_NEAR]))
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(3):
            stub.set(payload([PERSON, UNSECURED_NEAR]))
            time.sleep(0.03)
        wait_snapshot(client, lambda s: s["mission_state"] == "CRITICAL")
        alert_id = client.get("/api/safety/alerts").json()["active"][0]["id"]
        result = client.post(f"/api/safety/alerts/{alert_id}/ack", json={"note": "operator inspecting"}).json()
        assert result["found"] is True
        assert result["alert"]["acknowledged"] is True
        alert = client.get("/api/safety/alerts").json()["active"][0]
        assert alert["acknowledged"] is True
        assert alert["ack_note"] == "operator inspecting"
        assert client.get("/api/safety/snapshot").json()["monitor"]["state"] == "ACKNOWLEDGED"


def test_unknown_class_is_reported_never_claimed(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, TOOL_FAR, MYSTERY]))
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(3):
            stub.set(payload([PERSON, TOOL_FAR, MYSTERY]))
            time.sleep(0.03)
        snap = wait_snapshot(client, lambda s: "chicken_suit" in s["unclassified"])
        assert snap["unclassified"] == ["chicken_suit"]
        mystery = next(a for a in snap["assessments"] if a["object"] == "chicken_suit")
        assert mystery["hazard"] is False
        assert mystery["risk_level"] == "SAFE"
        assert "not present in the hazard knowledge base" in mystery["reason"]


# ------------------------------------------------- emergency / incidents / E2E


def test_astronaut_emergency_flow_end_to_end(tmp_path) -> None:
    stub = StubDetection(payload([PERSON]))
    client, incidents, transport = build_safety_client(tmp_path, stub, absent_frames=2)
    with client:
        # Start the camera too so evidence frames are captured.
        client.post("/api/camera/start")
        wait_ticks(client, 3)
        assert client.get("/api/safety/snapshot").json()["astronaut_in_view"] is True

        stub.set(payload([]))
        snap = wait_snapshot(client, lambda s: s["mission_state"] == "EMERGENCY")
        assert snap["emergency"]["confirmed"] is True
        assert snap["emergency"]["event_type"] == "ASTRONAUT_DOWN"
        assert snap["monitor"]["state"] == "EMERGENCY"

        # Incident recorded with evidence + escalation package (local only).
        incidents_list = incidents.incidents()
        assert len(incidents_list) == 1
        incident = incidents_list[0]
        assert incident.severity == "EMERGENCY"
        assert incident.state == "OPEN"
        incident_dir = incidents.root / incident.incident_id
        assert (incident_dir / "event.json").exists()
        assert (incident_dir / "metadata.json").exists()
        assert (incident_dir / "escalation.json").exists()
        package = json.loads((incident_dir / "escalation.json").read_text(encoding="utf-8"))
        assert package["_status"] == "EARTH_ESCALATION_PACKAGE_READY"
        assert "No real transmission interface" in package["_note"]
        frames = list(incident_dir.glob("frame_*.jpg"))
        assert len(frames) == 1, "camera was running so an evidence frame must be captured"

        # Station / mission-control panel saw the emergency.
        feed = transport.feed()
        assert len(feed) == 1
        assert feed[0].severity == "EMERGENCY"
        assert feed[0].incident_id == incident.incident_id
        station = client.get("/api/safety/station").json()
        assert station["feed"][0]["incident_id"] == incident.incident_id
        events = client.get("/api/safety/events").json()["events"]
        assert any(e["kind"] == "EMERGENCY_DETECTED" for e in events)
        assert any(e["kind"] == "EARTH_ESCALATION_READY" for e in events)
        status = client.get("/api/safety/status").json()
        assert status["escalations_ready"] == 1
        assert status["emergency_incidents"] == 1


def test_warning_near_astronaut_creates_warning_incident(tmp_path) -> None:
    cable = {"class_name": "loose_cable", "confidence": 0.85, "x1": 195, "y1": 15, "x2": 300, "y2": 25}
    stub = StubDetection(payload([PERSON, cable]))
    client, incidents, transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(4):
            stub.set(payload([PERSON, cable]))
            time.sleep(0.03)
        wait_snapshot(client, lambda s: any(a["object"] == "loose_cable" and a["near_astronaut"] for a in s["assessments"]))
        incidents_list = incidents.incidents()
        assert len(incidents_list) == 1
        assert incidents_list[0].severity == "WARNING"


def test_incidents_reload_from_disk_on_restart(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, UNSECURED_NEAR]))
    first_log = IncidentLog(root=tmp_path / "incidents", model_version="test")

    def make_app() -> TestClient:
        return TestClient(
            create_app(
                experiment=EXP,
                sim_script=FAST_SCRIPT,
                camera=MOCK_SETTINGS,
                detection_service=stub,
                safety_autostart=True,
                safety_poll_ms=10,
                safety_hazard_engine=HazardEngine(
                    environment_mode="microgravity", persist_frames=2, resolve_frames=2, stale_after_ms=60_000
                ),
                safety_emergency=EmergencyManager(backend="none"),
                safety_alerts=AlertManager(cooldown_ms=1),
                safety_incidents=first_log,
                safety_transport=LocalMissionControlTransport(),
            )
        )

    with make_app() as client:
        for _ in range(3):
            stub.set(payload([PERSON, UNSECURED_NEAR]))
            time.sleep(0.03)
        wait_snapshot(client, lambda s: s["mission_state"] == "CRITICAL")
        incident_id = first_log.incidents()[0].incident_id

    reloaded = IncidentLog(root=tmp_path / "incidents", model_version="test")
    assert reloaded.get(incident_id) is not None
    assert reloaded.get(incident_id).state == "OPEN"


# --------------------------------------------------------- degraded/failure paths


def test_camera_unavailable_never_advances_or_invents_data(tmp_path) -> None:
    off = payload([PERSON, TOOL_NEAR], enabled=False, status="disabled")
    stub = StubDetection(off)
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        snap = wait_snapshot(client, lambda s: s.get("feed_stale") is True)
        assert snap["assessments"] == []
        assert snap["mission_state"] == "NORMAL"
        assert snap["overall_risk_level"] == "SAFE"
        assert client.get("/api/safety/alerts").json()["active"] == []
        assert incidents.incidents() == []
        status = client.get("/api/safety/status").json()
        assert status["monitoring"] is True
        assert status["feed_stale"] is True


def test_stale_feed_keeps_hazard_but_never_auto_resolves(tmp_path) -> None:
    stub = StubDetection(payload([PERSON, UNSECURED_NEAR]))
    client, incidents, _transport = build_safety_client(tmp_path, stub)
    with client:
        for _ in range(3):
            stub.set(payload([PERSON, UNSECURED_NEAR]))
            time.sleep(0.03)
        wait_snapshot(client, lambda s: s["mission_state"] == "CRITICAL")
        # Feed dies -> scene retained but stale; CRITICAL state is NOT resolved away.
        stub.set(payload([PERSON], enabled=False, status="disabled"))
        body = wait_snapshot(client, lambda s: s.get("feed_stale") is True)
        assert body["mission_state"] in {"CRITICAL", "ACKNOWLEDGED"}
        assert body["overall_risk_level"] == "CRITICAL"


def test_yolo_missing_reports_error_without_silent_mock_fallback(tmp_path) -> None:
    detector = create_detector("yolo", model_path="definitely_missing_model.onnx")
    with TestClient(
        create_app(
            experiment=EXP,
            sim_script=FAST_SCRIPT,
            camera=MOCK_SETTINGS,
            detector=detector,
            safety_autostart=True,
            safety_poll_ms=10,
            safety_incidents=IncidentLog(root=tmp_path / "incidents", model_version="test"),
            safety_transport=LocalMissionControlTransport(),
        )
    ) as client:
        client.post("/api/camera/start")
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if client.get("/api/detection/status").json()["inferenceStatus"] == "error":
                break
            time.sleep(0.02)
        # Detection reports YOLO missing — never silently swapped for the mock.
        status = client.get("/api/detection/status").json()
        assert status["detector"] == "yolo"
        assert "not found" in (status["error"] or "")
        safety = client.get("/api/safety/status").json()
        assert safety["detector"] == "yolo"
        assert safety["detector_error"]
        assert safety["monitoring"] is True
        snap = client.get("/api/safety/snapshot").json()
        assert snap["assessments"] == []
        assert snap["mission_state"] == "NORMAL"
        assert client.get("/api/safety/alerts").json()["active"] == []
        assert client.get("/api/health").json()["status"] == "ok"


def test_detector_inference_failure_surfaces_error_no_fake_assessments(tmp_path) -> None:
    class FailingDetector:
        name = "failing"
        model_free = True

        def detect(self, frame, timestamp_ms=None):  # noqa: ANN001
            raise RuntimeError("boom")

        def load(self) -> None:
            return None

        def status(self):
            from ai.detection.types import DetectorStatus

            return DetectorStatus(detector_type=self.name, model_loaded=True)

        def close(self) -> None:
            return None

    with TestClient(
        create_app(
            experiment=EXP,
            sim_script=FAST_SCRIPT,
            camera=MOCK_SETTINGS,
            detector=FailingDetector(),
            safety_autostart=True,
            safety_poll_ms=10,
            safety_incidents=IncidentLog(root=tmp_path / "incidents", model_version="test"),
            safety_transport=LocalMissionControlTransport(),
        )
    ) as client:
        client.post("/api/camera/start")
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if client.get("/api/detection/status").json()["inferenceStatus"] == "error":
                break
            time.sleep(0.02)
        status = client.get("/api/detection/status").json()
        assert "boom" in (status["error"] or "")
        snap = client.get("/api/safety/snapshot").json()
        assert "boom" in snap["detector_error"]
        assert snap["assessments"] == []
        assert client.get("/api/safety/status").json()["monitoring"] is True


def test_demo_scene_runs_through_live_detection_pipeline(tmp_path) -> None:
    """MOCK_SCENE flows through the real DetectionService + mock camera into the
    safety service — the exact wiring a demo/`run_mock_demo.ps1` uses."""
    from app import config

    old = config.MOCK_SCENE
    config.MOCK_SCENE = "space_station"
    try:
        app = create_app(
            experiment=EXP,
            sim_script=FAST_SCRIPT,
            camera=MOCK_SETTINGS,
            detector=create_detector("mock", scene="space_station"),
            safety_autostart=True,
            safety_poll_ms=10,
            safety_incidents=IncidentLog(root=tmp_path / "incidents", model_version="test"),
            safety_transport=LocalMissionControlTransport(),
        )
        with TestClient(app) as client:
            client.post("/api/camera/start")
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                if client.get("/api/camera/status").json()["status"] == "connected":
                    break
                time.sleep(0.01)
            snap = wait_snapshot(
                client,
                lambda s: any(a["object"] == "floating_tool" and a["confirmed"] for a in s["assessments"]),
            )
            tool = next(a for a in snap["assessments"] if a["object"] == "floating_tool")
            assert tool["hazard"] is True
            assert tool["risk_level"] in {"WARNING", "CRITICAL"}
            assert snap["astronaut_in_view"] is True
            assert snap["mission_state"] in {"WARNING", "CRITICAL"}
            assert client.get("/api/safety/status").json()["detector"] == "mock"
    finally:
        config.MOCK_SCENE = old


def test_health_includes_safety(tmp_path) -> None:
    stub = StubDetection(payload([]))
    client, incidents, transport = build_safety_client(tmp_path, stub)
    with client:
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["safety_monitoring"] is True
        assert body["mission_state"] in {"NORMAL", "WARNING", "CRITICAL", "EMERGENCY"}
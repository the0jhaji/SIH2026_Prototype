"""Detection service + API tests.

Runs on the mock camera and an injected mock/failing detector — never touches
a physical device or model weights. Disabled mode and the "missing model
produces a clear error instead of crashing" contract are covered too.
"""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from camera import CameraSettings
from app import config
from app.detection_service import DetectionService
from app.experiment import load_experiment
from app.main import create_app

EXPERIMENTS = Path(__file__).resolve().parent.parent / "experiments"
EXP = load_experiment(EXPERIMENTS / "box_sequence.json")

FAST_SCRIPT = [{"delay_ms": 5, "activity": "PICK_MAIN_BOX", "confidence": 0.96}]

MOCK_SETTINGS = CameraSettings(mock=True, width=320, height=240, fps=120)

# Injected after app.main (which puts the repo root on sys.path):
from ai.detection.detector import create_detector  # noqa: E402
from ai.detection.types import DetectorStatus  # noqa: E402


class FailingDetector:
    """A detector whose inference always raises, to exercise error surfacing."""

    name = "failing"
    model_free = True

    def detect(self, frame, timestamp_ms=None):  # noqa: ANN001
        raise RuntimeError("boom")

    def load(self) -> None:
        return None

    def status(self) -> DetectorStatus:
        return DetectorStatus(detector_type=self.name, model_loaded=True)

    def close(self) -> None:
        return None


def make_client(detector=None) -> TestClient:
    return TestClient(
        create_app(
            experiment=EXP,
            sim_script=FAST_SCRIPT,
            camera=MOCK_SETTINGS,
            detector=detector,
        )
    )


def start_camera(client: TestClient) -> None:
    client.post("/api/camera/start")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if client.get("/api/camera/status").json()["status"] == "connected":
            return
        time.sleep(0.01)
    raise AssertionError("camera did not connect")


def wait_for_detection_status(client: TestClient, want: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/detection/status").json()
        if body["inferenceStatus"] == want:
            return body
        time.sleep(0.02)
    raise AssertionError(f"inferenceStatus {want!r} not reached")


def wait_for_stable_detections(client: TestClient, n: int, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/detections").json()
        if len(body.get("detections", [])) >= n:
            return body
        time.sleep(0.02)
    raise AssertionError(f"stable detections {n} not reached")


def test_default_config_is_off() -> None:
    assert config.DETECTION_ENABLED is False


def test_disabled_service_is_inert() -> None:
    from camera import CameraManager

    svc = DetectionService(CameraManager(MOCK_SETTINGS), enabled=False)
    assert svc.is_enabled() is False
    assert svc.status()["enabled"] is False
    assert svc.status()["inferenceStatus"] == "disabled"
    latest = svc.latest()
    assert latest["enabled"] is False
    assert latest["detections"] == []
    svc.close()


def test_api_disabled_endpoints_serve_clean_payloads() -> None:
    with make_client() as client:
        status = client.get("/api/detection/status").json()
        assert status["enabled"] is False
        assert status["inferenceStatus"] == "disabled"
        dets = client.get("/api/detections").json()
        assert dets["enabled"] is False
        assert dets["detections"] == []


def test_mock_detection_end_to_end() -> None:
    detector = create_detector("mock")
    with make_client(detector=detector) as client:
        status = client.get("/api/detection/status").json()
        assert status["enabled"] is True
        assert status["detector"] == "mock"
        assert status["modelLoaded"] is True
        assert status["inferenceStatus"] == "idle"

        start_camera(client)
        ok = wait_for_detection_status(client, "ok")
        assert ok["rawDetectionCount"] >= 3  # raw feed debounced into stable

        dets = wait_for_stable_detections(client, 3)
        assert dets["enabled"] is True
        assert dets["frameWidth"] == 320
        assert dets["frameHeight"] == 240
        assert dets["lastInferenceMs"] is not None
        assert [d["class_name"] for d in dets["detections"]] == [
            "person",
            "red_box",
            "yellow_box",
        ]
        assert [d["confidence"] for d in dets["detections"]] == [0.95, 0.91, 0.89]
        for d in dets["detections"]:
            assert set(d) == {"class_name", "confidence", "x1", "y1", "x2", "y2", "timestamp"}
            assert 0 <= d["x1"] < d["x2"] <= 320
            assert 0 <= d["y1"] < d["y2"] <= 240
        # Raw single-frame view is still available for debugging.
        assert [d["class_name"] for d in dets["rawDetections"]] == [
            "person",
            "red_box",
            "yellow_box",
        ]

        # MJPEG route untouched: camera still streams with detection on.
        assert client.get("/api/camera/snapshot").status_code == 200


def test_detector_failure_surfaces_error_but_app_survives() -> None:
    with make_client(detector=FailingDetector()) as client:
        start_camera(client)
        status = wait_for_detection_status(client, "error")
        assert "boom" in status["error"]
        assert status["modelLoaded"] is True
        # App keeps working: health + camera + detection endpoints all live.
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/detections").json()["detections"] == []
        dets = client.get("/api/detections").json()
        assert dets["inferenceStatus"] == "error"


def test_detection_service_forwards_dual_model_paths(monkeypatch) -> None:
    from camera import CameraManager

    from ai.detection import detector as detector_module

    captured: dict = {}
    real_factory = detector_module.create_detector

    def fake_factory(kind, **kwargs):
        captured["kind"] = kind
        captured.update(kwargs)
        return real_factory("mock")

    monkeypatch.setattr(detector_module, "create_detector", fake_factory)
    service = DetectionService(
        CameraManager(MOCK_SETTINGS),
        enabled=True,
        kind="dual",
        general_model_path="general.onnx",
        custom_model_path="custom.onnx",
        unknown_enabled=False,
    )
    service.stop()

    assert captured["kind"] == "dual"
    assert captured["general_model_path"] == "general.onnx"
    assert captured["custom_model_path"] == "custom.onnx"


def test_missing_yolo_weights_reports_clear_error() -> None:
    detector = create_detector("yolo", model_path="definitely_missing_model.onnx")
    with make_client(detector=detector) as client:
        status = client.get("/api/detection/status").json()
        assert status["enabled"] is True
        assert status["detector"] == "yolo"
        assert status["modelLoaded"] is False

        start_camera(client)
        failed = wait_for_detection_status(client, "error")
        assert failed["modelLoaded"] is False
        assert "not found" in (failed["error"] or "")
        # App stays healthy and other endpoints respond.
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/camera/status").json()["status"] == "connected"
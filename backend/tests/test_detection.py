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


def test_frame_size_is_served_before_the_first_inference() -> None:
    """The overlay divides pixel coordinates by frameWidth/frameHeight, so a
    null frame size means "draw nothing". The dashboard must be able to size the
    feed as soon as the camera delivers a frame, not only after inference."""
    detector = create_detector("mock")
    with make_client(detector=detector) as client:
        # Enabled, camera idle: nothing is being served, so no frame geometry.
        idle = client.get("/api/detections").json()
        assert idle["frameWidth"] is None
        assert idle["frameHeight"] is None
        assert idle["frameSizeSource"] == "unknown"

        client.post("/api/camera/start")
        deadline = time.monotonic() + 5.0
        payload = idle
        while time.monotonic() < deadline:
            payload = client.get("/api/detections").json()
            if payload["frameWidth"] is not None:
                break
            time.sleep(0.01)
        assert payload["frameWidth"] == 320
        assert payload["frameHeight"] == 240
        assert payload["frameSizeSource"] in {"camera", "inference"}


def test_disabled_service_never_claims_a_frame_size() -> None:
    """A disabled detector with a configured camera must not report a frame.

    Consumers read a non-null frame size as "a frame is being served"
    (attendance staleness, hazard proximity); inventing one from the camera
    config would let those advance on a dead feed."""
    from camera import CameraManager

    svc = DetectionService(CameraManager(MOCK_SETTINGS), enabled=False)
    try:
        assert svc.latest()["frameWidth"] is None
        assert svc.latest()["frameSizeSource"] == "disabled"
    finally:
        svc.close()


def test_detection_boxes_are_clamped_to_the_detection_frame() -> None:
    """Boxes are pixels of the frame the detector saw. The EMA tracker only
    enforces the lower bound, so an out-of-range box from any detector would
    reach the overlay, attendance geometry and hazard proximity un-clamped."""
    from camera import CameraManager

    from ai.detection.types import Detection, now_ms

    class OversizedDetector:
        """Emits boxes well outside the frame on both sides."""

        name = "oversized"
        model_free = True

        def detect(self, frame, timestamp_ms=None):  # noqa: ANN001
            ts = timestamp_ms or now_ms()
            return [
                Detection("person", 0.9, -40, -30, frame.shape[1] + 90, frame.shape[0] + 70, ts),
                Detection("bottle", 0.8, 5, 5, 120, 150, ts),
            ]

        def load(self) -> None:
            return None

        def status(self) -> DetectorStatus:
            return DetectorStatus(detector_type=self.name, model_loaded=True)

        def close(self) -> None:
            return None

    svc = DetectionService(
        CameraManager(MOCK_SETTINGS),
        detector=OversizedDetector(),
        enabled=True,
        debounce_frames=1,
    )
    try:
        svc._camera.start()  # the service never starts the camera for you
        deadline = time.monotonic() + 5.0
        boxes: list[dict] = []
        while time.monotonic() < deadline:
            boxes = svc.latest()["detections"]
            if boxes:
                break
            time.sleep(0.01)
        assert boxes, "detector never produced a stable box"
        for d in boxes:
            assert 0 <= d["x1"] < d["x2"] <= 320
            assert 0 <= d["y1"] < d["y2"] <= 240
        person = next(d for d in boxes if d["class_name"] == "person")
        assert (person["x1"], person["y1"], person["x2"], person["y2"]) == (0, 0, 320, 240)
    finally:
        svc.stop()


def test_unknown_detections_carry_a_stable_instance_id() -> None:
    """The overlay and the attendance chain both key on instance_id; without it
    an unknown track cannot be followed or styled."""
    from camera import CameraManager

    class UnknownDetector:
        """Only ever proposes unknown objects, so the generic chain runs too."""

        name = "unknown-only"
        model_free = True

        def detect(self, frame, timestamp_ms=None):  # noqa: ANN001
            return []

        def load(self) -> None:
            return None

        def status(self) -> DetectorStatus:
            return DetectorStatus(detector_type=self.name, model_loaded=True, classes=("unknown_object",))

        def close(self) -> None:
            return None

    svc = DetectionService(
        CameraManager(MOCK_SETTINGS),
        detector=UnknownDetector(),
        enabled=True,
        debounce_frames=1,
        unknown_enabled=True,
    )
    try:
        svc._camera.start()  # the service never starts the camera for you
        deadline = time.monotonic() + 10.0
        unknown: list[dict] = []
        while time.monotonic() < deadline:
            unknown = svc.latest()["unknownDetections"]
            if unknown:
                break
            time.sleep(0.02)
        assert unknown, "generic proposer produced no unknown track"
        for d in unknown:
            assert d["class_name"] == "unknown_object"
            assert d["instance_id"], "unknown detection must carry an instance id"
        # Known feed stays separate: the proposer never merges into it.
        assert all(d["class_name"] != "unknown_object" for d in svc.latest()["detections"])
    finally:
        svc.stop()


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
"""Camera manager + API tests. Everything runs on the mock camera so the
suite never touches physical hardware."""

import asyncio
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from camera import CameraManager, CameraSettings
from camera.capture import MockCamera
from app.experiment import load_experiment
from app.main import create_app

EXPERIMENTS = Path(__file__).resolve().parent.parent / "experiments"
EXP = load_experiment(EXPERIMENTS / "box_sequence.json")

FAST_SCRIPT = [{"delay_ms": 5, "activity": "PICK_MAIN_BOX", "confidence": 0.96}]

MOCK_SETTINGS = CameraSettings(mock=True, width=320, height=240, fps=120)


def make_client(camera: CameraSettings = MOCK_SETTINGS) -> TestClient:
    return TestClient(create_app(experiment=EXP, sim_script=FAST_SCRIPT, camera=camera))


def wait_for(client: TestClient, predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = client.get("/api/camera/status").json()
        if predicate(info):
            return info
        time.sleep(0.01)
    raise AssertionError("condition not met within timeout")


def test_manager_initial_disconnected() -> None:
    manager = CameraManager(CameraSettings(mock=True))
    assert manager.status.value == "disconnected"
    assert manager.latest_frame() is None
    info = manager.info()
    assert info["status"] == "disconnected"
    assert info["running"] is False
    assert info["mock"] is True


def test_manager_start_exposes_latest_frame() -> None:
    manager = CameraManager(MOCK_SETTINGS)
    info = manager.start()
    assert info["status"] != "error"

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and manager.status.value != "connected":
        time.sleep(0.01)
    assert manager.status.value == "connected"
    assert manager.is_running() is True

    frame = manager.latest_frame()
    assert frame is not None
    assert frame.shape == (240, 320, 3)
    assert frame.dtype == np.uint8

    frame_id, jpeg = manager.latest_jpeg()
    assert frame_id >= 1
    assert jpeg[:2] == b"\xff\xd8"  # JPEG start-of-image marker

    manager.stop()
    assert manager.status.value == "disconnected"
    assert manager.is_running() is False


def test_api_status_and_control_cycle() -> None:
    with make_client() as client:
        assert client.get("/api/camera/status").json()["status"] == "disconnected"
        assert client.get("/api/camera/snapshot").status_code == 503
        assert client.get("/api/camera/stream").status_code == 503

        start_info = client.post("/api/camera/start").json()
        assert start_info["status"] != "error"
        connected = wait_for(client, lambda i: i["status"] == "connected")
        assert connected["source"] == "mock"
        assert connected["width"] == 320
        assert connected["height"] == 240
        assert connected["mock"] is True

        # Start while running is a no-op.
        again = client.post("/api/camera/start").json()
        assert again["running"] is True
        assert again["status"] == "connected"

        # A fresh snapshot is served once frames exist.
        snapshot = client.get("/api/camera/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.headers["content-type"].startswith("image/jpeg")
        assert snapshot.content[:2] == b"\xff\xd8"

        stopped = client.post("/api/camera/stop").json()
        assert stopped["status"] == "disconnected"
        assert stopped["running"] is False

        # Reconnect after stop works.
        wait_for(client, lambda i: i["status"] == "disconnected")
        client.post("/api/camera/start")
        connected_again = wait_for(client, lambda i: i["status"] == "connected")
        assert connected_again["running"] is True


def test_mjpeg_stream_chunks_have_boundary_and_jpeg() -> None:
    """Drive the MJPEG feed at the source of truth.

    The route itself is covered for its offline contract (503 above); live
    multipart delivery through TestClient's httpx streaming is unreliable on
    Python 3.14 (prod path is plain uvicorn + StreamingResponse).
    """
    import asyncio

    with make_client() as client:
        client.post("/api/camera/start")
        wait_for(client, lambda i: i["status"] == "connected")
        manager = client.app.state.camera_manager

        async def grab(n: int) -> list[bytes]:
            chunks: list[bytes] = []
            async for chunk in manager.mjpeg_frames():
                chunks.append(chunk)
                if len(chunks) == n:
                    break
            return chunks

        chunks = asyncio.run(asyncio.wait_for(grab(2), timeout=5.0))
        assert len(chunks) == 2
        for chunk in chunks:
            assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
            assert b"\xff\xd8" in chunk  # JPEG start-of-image marker


def test_open_failure_reports_error_and_recovers(monkeypatch) -> None:
    original_open = MockCamera.open

    def broken_open(self) -> bool:  # noqa: ANN001
        return False

    with make_client() as client:
        monkeypatch.setattr(MockCamera, "open", broken_open)
        client.post("/api/camera/start")
        info = wait_for(client, lambda i: i["status"] == "error")
        assert info["running"] is False
        assert info["error"]
        # A later start with a healthy camera recovers.
        monkeypatch.setattr(MockCamera, "open", original_open)
        client.post("/api/camera/start")
        connected = wait_for(client, lambda i: i["status"] == "connected")
        assert connected["running"] is True


def test_lifespan_shutdown_cleans_up() -> None:
    manager = CameraManager(MOCK_SETTINGS)
    manager.start()
    manager.close()
    assert manager.status.value == "disconnected"
    assert manager.latest_frame() is None
"""Camera manager + API tests. Everything runs on the mock camera so the
suite never touches physical hardware."""

import asyncio
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from camera import CameraManager, CameraSettings
from camera.capture import MockCamera, select_backend, validate_frame
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


# ---------------------------------------------------------------------------
# Frame validation + backend fallback (no physical device touched).
# ---------------------------------------------------------------------------


def test_validate_frame_rejects_black_but_accepts_real_pixels() -> None:
    black = np.zeros((240, 320, 3), dtype=np.uint8)
    ok, reason = validate_frame(black, reject_black=True)
    assert ok is False
    assert "blank/black" in reason

    noisy = black.copy()
    noisy[::8, ::8] = 128  # sparse but real (mean/σ above the black floor)
    ok, reason = validate_frame(noisy, reject_black=True)
    assert ok is True

    ok, reason = validate_frame(None, reject_black=True)
    assert ok is False and reason == "no frame returned"

    # reject_black=False makes even a zero frame structurally valid.
    ok, reason = validate_frame(black, reject_black=False)
    assert ok is True


class _BlackReader:
    """FrameReader that always delivers pure-black frames."""

    name = "webcam"

    def __init__(self, settings: CameraSettings) -> None:
        self.settings = settings
        self.backend = "dshow"
        self.diagnostics = {"probes": ["dshow: black-frame test stub"]}

    def open(self) -> bool:
        return True

    def read(self):
        return np.zeros((self.settings.height, self.settings.width, 3), dtype=np.uint8)

    def release(self) -> None:
        pass


def test_black_feed_never_connects(monkeypatch) -> None:
    with make_client() as client:
        monkeypatch.setattr(CameraManager, "_make_reader", lambda self: _BlackReader(self.settings))
        client.post("/api/camera/start")
        info = wait_for(client, lambda i: i["status"] == "error")
        assert info["running"] is False
        assert info["frameCount"] == 0
        assert "blank/black" in info["error"]
        assert info["backend"] == "dshow"


class _ProbeHandle:
    """Fake capture handle: yields the given sequence of frames/errors."""

    def __init__(self, frames):
        self._frames = list(frames)

    def read(self):
        got = self._frames.pop(0) if self._frames else None
        if isinstance(got, Exception):
            raise got
        return got


def test_select_backend_adopts_first_valid_backend() -> None:
    def open_fn(name):
        return _ProbeHandle([]) if False else _ProbeHandle([None, np.ones((8, 8, 3), dtype=np.uint8) * 255])

    chosen, handle, attempts = select_backend(
        ("msmf", "dshow"),
        open_fn=open_fn,
        read_fn=lambda h: h.read(),
        release_fn=lambda h: None,
        reject_black=True,
        max_warmup=3,
    )
    assert chosen == "msmf"
    assert handle is not None
    assert attempts[0].valid_frame is True


def test_select_backend_skips_black_backend_and_takes_next_valid() -> None:
    def open_fn(name):
        if name == "msmf":
            return _ProbeHandle([np.zeros((8, 8, 3), dtype=np.uint8), np.zeros((8, 8, 3), dtype=np.uint8)])
        return _ProbeHandle([np.ones((8, 8, 3), dtype=np.uint8) * 255])

    chosen, _, attempts = select_backend(
        ("msmf", "dshow"),
        open_fn=open_fn,
        read_fn=lambda h: h.read(),
        release_fn=lambda h: None,
        reject_black=True,
        max_warmup=2,
    )
    assert chosen == "dshow"
    assert attempts[0].opened is True and attempts[0].valid_frame is False
    assert attempts[1].valid_frame is True


def test_select_backend_reports_none_valid_with_diagnostics() -> None:
    def open_fn(name):
        return _ProbeHandle([np.zeros((8, 8, 3), dtype=np.uint8)])

    chosen, handle, attempts = select_backend(
        ("msmf", "dshow"),
        open_fn=open_fn,
        read_fn=lambda h: h.read(),
        release_fn=lambda h: None,
        reject_black=True,
        max_warmup=1,
    )
    assert chosen is None and handle is None
    assert len(attempts) == 2
    assert all(a.opened and not a.valid_frame for a in attempts)  # honesty: no valid feed


def test_select_backend_records_exceptions_from_read() -> None:
    boom = RuntimeError("MF_E_INVALIDREQUEST (0x800706BE)")

    def open_fn(name):
        return _ProbeHandle([boom, boom])

    chosen, handle, attempts = select_backend(
        ("msmf",),
        open_fn=open_fn,
        read_fn=lambda h: h.read(),
        release_fn=lambda h: None,
        max_warmup=2,
    )
    assert chosen is None
    # All probe reads were recorded as failed (the exact error text lives in the
    # raised exception; here we verify the failure was swallowed, not fatal).
    assert attempts[0].reads_failed == 2
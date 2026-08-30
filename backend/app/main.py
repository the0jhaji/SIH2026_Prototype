"""Astra AI backend.

REST control plane + WebSocket event stream. The state machine is the only
authority on step validity; the simulated perception source feeds it the same
Detection shapes the future camera pipeline will.

Run:
    uvicorn app.main:app --reload --port 8000

Camera:
    GET  /api/camera/status   state + settings
    POST /api/camera/start     start capture (real webcam or mock)
    POST /api/camera/stop      stop and release the device
    GET  /api/camera/stream    MJPEG multipart stream (browser <img>)
    GET  /api/camera/snapshot  single JPEG frame

Detection (Phase 3, off by default — DETECTION_ENABLED=true):
    GET /api/detection/status  detector health (enabled, model, inference)
    GET /api/detections        latest structured detections + frame size
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from camera import CameraManager, CameraSettings

from . import config
from .activity_perception import LiveActivityPerception, MockActivityPerception
from .detection_service import DetectionService
from .experiment import load_active_experiment
from .log_store import LogStore
from .manager import ConnectionManager
from .schemas import ExperimentDef
from .service import ExperimentService
from .simulator import SimulatedPerception

logging.basicConfig(level=logging.INFO)


def camera_settings_from_config() -> CameraSettings:
    return CameraSettings(
        camera_index=config.CAMERA_INDEX,
        width=config.CAMERA_WIDTH,
        height=config.CAMERA_HEIGHT,
        fps=config.CAMERA_FPS,
        mock=config.CAMERA_MOCK,
        jpeg_quality=config.CAMERA_JPEG_QUALITY,
    )


def create_app(
    experiment: Optional[ExperimentDef] = None,
    sim_script: Optional[list] = None,
    camera: Optional[CameraSettings] = None,
    detector=None,
    activity_backend: Optional[str] = None,
    detection_service=None,
) -> FastAPI:
    """Build the FastAPI app.

    ``detector`` injects a ready-made ``ai.detection`` detector (tests use a
    mock); when omitted the app follows the ``DETECTION_*`` config env vars.
    ``detection_service`` injects the whole service (tests use a stub with a
    ``latest()``/``status()`` contract); when omitted it is built internally.

    ``activity_backend`` (``mock`` | ``live`` | ``sim``) overrides
    ``ACTIVITY_BACKEND`` for tests; when ``sim_script`` is injected the
    simulator is always used so existing callers keep the scripted feed.
    """
    exp = experiment or load_active_experiment()
    manager = ConnectionManager()
    store = LogStore()
    service = ExperimentService(exp, manager, store)
    simulator = SimulatedPerception(sim_script)
    # A sim_script explicitly opts into the scripted feed; otherwise the
    # ACTIVITY_BACKEND config picks the perception source.
    perception_backend = (
        "sim" if sim_script is not None else (activity_backend or config.ACTIVITY_BACKEND)
    ).strip().lower()
    mock_perception = MockActivityPerception(exp, config.ACTIVITY_POLL_MS)
    camera_manager = CameraManager(camera or camera_settings_from_config())
    if detection_service is None:
        detection_service = DetectionService(
            camera_manager,
            detector=detector,
            enabled=config.DETECTION_ENABLED or detector is not None,
            kind=config.DETECTION_BACKEND,
            model_path=config.DETECTION_MODEL_PATH,
            conf_threshold=config.DETECTION_CONF_THRESHOLD,
            poll_ms=config.DETECTION_POLL_MS,
        )
    live_perception = LiveActivityPerception(
        exp,
        detection_service,
        poll_ms=config.ACTIVITY_POLL_MS,
        conf_threshold=config.DETECTION_CONF_THRESHOLD,
        stale_after_ms=config.ACTIVITY_STALE_MS,
        current_index=lambda: service.session.current_step_index,
    )

    sources = {
        "mock": mock_perception,
        "live": live_perception,
        "sim": simulator,
    }

    def perception_source():
        return sources.get(perception_backend, live_perception)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await service.stop()
        close = getattr(detection_service, "close", None)
        if close is not None:
            close()
        camera_manager.close()

    app = FastAPI(title="Astra AI Backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.service = service
    app.state.simulator = simulator
    app.state.mock_perception = mock_perception
    app.state.live_perception = live_perception
    app.state.camera_manager = camera_manager
    app.state.detection_service = detection_service

    # ------------------------------------------------------------------ REST

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "source": perception_source().name,
            "experiment_id": exp.id,
            "clients": manager.count(),
            "camera_status": camera_manager.status.value,
        }

    @app.get("/api/experiment")
    async def get_experiment() -> dict:
        return {"experiment": exp.model_dump(), "state": service.snapshot()}

    @app.get("/api/experiment/status")
    async def get_status() -> dict:
        return service.snapshot()

    @app.post("/api/experiment/start")
    async def start() -> dict:
        return await service.start(perception_source())

    @app.post("/api/experiment/stop")
    async def stop() -> dict:
        return await service.stop()

    @app.get("/api/logs")
    async def logs() -> dict:
        return {"events": store.all()}

    # ---------------------------------------------------------------- Camera

    @app.get("/api/camera/status")
    async def camera_status() -> dict:
        return camera_manager.info()

    @app.post("/api/camera/start")
    async def camera_start() -> dict:
        return camera_manager.start()

    @app.post("/api/camera/stop")
    async def camera_stop() -> dict:
        return camera_manager.stop()

    @app.get("/api/camera/stream")
    async def camera_stream() -> StreamingResponse:
        if not camera_manager.is_running():
            raise HTTPException(status_code=503, detail="Camera is not streaming")
        return StreamingResponse(
            camera_manager.mjpeg_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/camera/snapshot")
    async def camera_snapshot() -> Response:
        current = camera_manager.latest_jpeg()
        if current is None or not camera_manager.is_running():
            raise HTTPException(status_code=503, detail="Camera is not streaming")
        return Response(
            content=current[1],
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    # -------------------------------------------------------------- Detection

    @app.get("/api/detection/status")
    async def detection_status() -> dict:
        return detection_service.status()

    @app.get("/api/detections")
    async def detections() -> dict:
        return detection_service.latest()

    # ---------------------------------------------------------------- WebSocket

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            await websocket.send_json({"type": "state", "data": service.snapshot()})
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception:  # noqa: BLE001 - drop dead connections
            manager.disconnect(websocket)

    return app


app = create_app()
"""Astra AI — Astronaut Safety & Hazard Monitoring.

REST control plane + WebSocket event stream for the NEW core purpose: offline,
local-first astronaut safety and hazard detection. The experiment/state-machine
pipeline is retained as a decoupled legacy demo fixture (routes below still
exist for it); the safety monitor owns the active risk assessment.

Run:
    uvicorn app.main:app --reload --port 8000

Camera:
    GET  /api/camera/status   state + settings
    POST /api/camera/start     start capture (real webcam or mock)
    POST /api/camera/stop      stop and release the device
    GET  /api/camera/stream    MJPEG multipart stream (browser <img>)
    GET  /api/camera/snapshot  single JPEG frame

Detection (off by default — DETECTION_ENABLED=true):
    GET /api/detection/status  detector health (enabled, model, inference)
    GET /api/detections        latest structured detections + frame size

Safety (new core, on by default):
    GET  /api/safety/status                     monitor + pipeline health
    GET  /api/safety/snapshot                   mission state + assessments
    POST /api/safety/start | stop               control the monitor loop
    GET  /api/safety/alerts                     active + recent alerts
    POST /api/safety/alerts/{id}/ack            acknowledge an alert
    GET  /api/safety/incidents                  incident history
    GET  /api/safety/incidents/{id}             incident + evidence detail
    GET  /api/safety/station                    mission-control station feed
    GET  /api/safety/events                     safety event log
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from camera import CameraManager, CameraSettings

from . import config
from .activity_perception import LiveActivityPerception, MockActivityPerception
from .attendance import AttendanceMonitor
from .detection_service import DetectionService
from .experiment import load_active_experiment
from .experiment_log import ExperimentLogger
from .experiment_state import ExperimentStateEngine
from .log_store import LogStore
from .manager import ConnectionManager
from .safety.alert_manager import AlertManager
from .safety.emergency import EmergencyManager
from .safety.hazard_engine import engine_from_config
from .safety.incidents import IncidentLog
from .safety.monitor import SafetyMonitor
from .safety.safety_service import SafetyService
from .safety.transports import LocalMissionControlTransport
from .schemas import ExperimentDef
from .service import ExperimentService
from .simulator import SimulatedPerception
from .voice_alert import VoiceAlertService

logging.basicConfig(level=logging.INFO)


def camera_settings_from_config() -> CameraSettings:
    return CameraSettings(
        camera_index=config.CAMERA_INDEX,
        width=config.CAMERA_WIDTH,
        height=config.CAMERA_HEIGHT,
        fps=config.CAMERA_FPS,
        mock=config.CAMERA_MOCK,
        jpeg_quality=config.CAMERA_JPEG_QUALITY,
        backend=config.CAMERA_BACKEND,
        reject_black=config.CAMERA_REJECT_BLACK,
        warmup_frames=config.CAMERA_WARMUP_FRAMES,
    )


def create_app(
    experiment: Optional[ExperimentDef] = None,
    sim_script: Optional[list] = None,
    camera: Optional[CameraSettings] = None,
    detector=None,
    activity_backend: Optional[str] = None,
    detection_service=None,
    *,
    attendance_monitor=None,
    safety_service=None,
    safety_hazard_engine=None,
    safety_emergency=None,
    safety_alerts=None,
    safety_incidents=None,
    safety_transport=None,
    safety_autostart: Optional[bool] = None,
    safety_poll_ms: Optional[int] = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``detector`` injects a ready-made ``ai.detection`` detector (tests use a
    mock); when omitted the app follows the ``DETECTION_*`` config env vars.
    ``detection_service`` injects the whole service (tests use a stub with a
    ``latest()``/``status()`` contract); when omitted it is built internally.

    ``activity_backend`` (``mock`` | ``live`` | ``sim``) overrides
    ``ACTIVITY_BACKEND`` for tests; when ``sim_script`` is injected the
    simulator is always used so existing callers keep the scripted feed.

    The ``safety_*`` parameters inject the Astronaut Safety pipeline pieces
    (tests) or let tests slow/fast the monitor loop / disable autostart.
    """
    exp = experiment or load_active_experiment()
    manager = ConnectionManager()
    store = LogStore()

    # --- Experiment state engine (rich lifecycle + temporal confirmation) ---
    voice_service = VoiceAlertService()
    experiment_logger = ExperimentLogger()

    def _engine_ws_broadcast(event_type: str, data: dict) -> None:
        asyncio.create_task(manager.broadcast({"type": event_type, "data": data}))

    state_engine = ExperimentStateEngine(
        exp,
        voice=voice_service,
        log=experiment_logger,
        broadcast=_engine_ws_broadcast,
    )

    def _on_detection_for_engine(detection):
        state_engine.on_detection(detection)

    service = ExperimentService(
        exp, manager, store, detection_callback=_on_detection_for_engine,
    )
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
            general_model_path=config.DETECTION_GENERAL_MODEL_PATH,
            custom_model_path=config.DETECTION_CUSTOM_MODEL_PATH,
            conf_threshold=config.DETECTION_CONF_THRESHOLD,
            poll_ms=config.DETECTION_POLL_MS,
            target_fps=config.DETECTION_FPS,
            trace=config.DETECT_LOG_ENABLED,
            scene=config.MOCK_SCENE or None,
            cv_threads=config.DETECTION_CV_THREADS if config.DETECTION_CV_THREADS > 0 else None,
            debounce_frames=config.DETECTION_DEBOUNCE_FRAMES,
            ema_alpha=config.DETECTION_EMA_ALPHA,
            unknown_enabled=config.UNKNOWN_DETECTION_ENABLED,
            unknown_min_area=config.UNKNOWN_MIN_AREA,
            unknown_overlap_iou=config.UNKNOWN_OVERLAP_IOU,
            unknown_motion_threshold=config.UNKNOWN_MOTION_THRESHOLD,
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

    # ------------------------------------------------- Astronaut safety (core)

    incidents_root = config.DATA_DIR / "incidents"
    detection_status = detection_service.status()
    model_version = (
        f"{detection_status.get('detector') or config.DETECTION_BACKEND}"
        f"@{detection_status.get('modelPath') or 'no-model'}"
    )
    if safety_service is None:
        safety_engine = safety_hazard_engine or engine_from_config()
        safety_service = SafetyService(
            detection_service=detection_service,
            camera_manager=camera_manager,
            manager=manager,
            store=LogStore(),
            engine=safety_engine,
            emergency=safety_emergency or EmergencyManager(
                backend=config.EMERGENCY_BACKEND,
                absent_frames=config.EMERGENCY_ABSENT_FRAMES,
                static_frames=config.EMERGENCY_STATIC_FRAMES,
            ),
            monitor=SafetyMonitor(resolve_cycles=config.SAFETY_RESOLVE_FRAMES),
            alerts=safety_alerts or AlertManager(cooldown_ms=config.ALERT_COOLDOWN_MS),
            incidents=safety_incidents or IncidentLog(root=incidents_root, model_version=model_version),
            transport=safety_transport or LocalMissionControlTransport(),
            poll_ms=safety_poll_ms if safety_poll_ms is not None else config.SAFETY_POLL_MS,
            escalate_enabled=config.EARTH_ESCALATION_ENABLED,
            escalate_min_level=config.EARTH_ESCALATION_MIN_LEVEL,
            model_version=model_version,
            voice=voice_service,
        )
    safety_autostart = config.SAFETY_ENABLED if safety_autostart is None else safety_autostart

    # Attendance (held/unattended) monitor — consumes the unknown-object feed.
    if attendance_monitor is None:
        attendance_monitor = AttendanceMonitor(
            detection_service.latest,
            poll_ms=config.ATTENDANCE_POLL_MS,
            held_frames=config.ATTENDANCE_HELD_FRAMES,
            unattended_frames=config.ATTENDANCE_UNATTENDED_FRAMES,
            track_lost_frames=config.ATTENDANCE_TRACK_LOST_FRAMES,
            arm_reach=config.ATTENDANCE_ARM_REACH,
            upper_body=config.ATTENDANCE_UPPER_BODY,
            unattended_timeout_ms=config.UNATTENDED_TIMEOUT_MS,
            proximity=config.UNATTENDED_PROXIMITY,
            containment=config.UNATTENDED_CONTAINMENT,
            container_classes=config.UNATTENDED_CONTAINER_CLASSES,
            tracked_classes=config.UNATTENDED_TRACKED_CLASSES,
            alerts=AlertManager(cooldown_ms=config.ALERT_COOLDOWN_MS),
        )

    def _broadcast_attendance(event: dict) -> None:
        asyncio.create_task(manager.broadcast({"type": "attendance_event", "data": event}))

    attendance_monitor.set_broadcast(_broadcast_attendance)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if safety_autostart:
            try:
                await safety_service.start()
            except Exception:  # noqa: BLE001 - safety must never block boot
                logging.getLogger("astraai.safety").exception("Safety autostart failed")
            try:
                await attendance_monitor.start()
            except Exception:  # noqa: BLE001 - attendance must never block boot
                logging.getLogger("astraai.attendance").exception("Attendance autostart failed")
        yield
        await attendance_monitor.stop()
        await safety_service.stop()
        await service.stop()
        voice_service.close()
        experiment_logger.close()
        close = getattr(detection_service, "close", None)
        if close is not None:
            close()
        camera_manager.close()

    app = FastAPI(
        title="Astra AI — Astronaut Safety & Hazard Monitoring",
        version="0.2.0",
        lifespan=lifespan,
    )
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
    app.state.state_engine = state_engine
    app.state.simulator = simulator
    app.state.mock_perception = mock_perception
    app.state.live_perception = live_perception
    app.state.camera_manager = camera_manager
    app.state.detection_service = detection_service
    app.state.safety_service = safety_service
    app.state.attendance_monitor = attendance_monitor

    # ------------------------------------------------------------------ REST

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "source": perception_source().name,
            "experiment_id": exp.id,
            "clients": manager.count(),
            "camera_status": camera_manager.status.value,
            "mission_state": safety_service.status()["mission_state"],
            "safety_monitoring": safety_service.is_monitoring(),
        }

    @app.get("/api/experiment")
    async def get_experiment() -> dict:
        return {
            "experiment": exp.model_dump(),
            "state": service.snapshot(),
            "engine": state_engine.snapshot(),
        }

    @app.get("/api/experiment/status")
    async def get_status() -> dict:
        snap = service.snapshot()
        snap["engine"] = state_engine.snapshot()
        return snap

    @app.post("/api/experiment/start")
    async def start() -> dict:
        return await service.start(perception_source())

    @app.post("/api/experiment/stop")
    async def stop() -> dict:
        return await service.stop()

    @app.get("/api/logs")
    async def logs() -> dict:
        return {"events": store.all()}

    # ------------------------------------------------- Experiment state engine

    @app.get("/api/experiment/v2/status")
    async def engine_status() -> dict:
        return state_engine.snapshot()

    @app.get("/api/experiment/v2/voice")
    async def engine_voice() -> dict:
        return {"health": voice_service.health, "queue_size": voice_service.queue_size}

    @app.post("/api/experiment/v2/start")
    async def engine_start() -> dict:
        if state_engine.state != "NOT_STARTED" and state_engine.state in (
            "COMPLETED", "ABORTED",
        ):
            return state_engine.snapshot()
        return state_engine.start()

    @app.post("/api/experiment/v2/stop")
    async def engine_stop() -> dict:
        return state_engine.stop()

    @app.get("/api/experiment/v2/log")
    async def engine_log() -> dict:
        log_path = experiment_logger.log_path
        if log_path is None or not log_path.exists():
            return {"events": [], "run_id": None}
        lines = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                import json
                lines.append(json.loads(line))
        return {"events": lines, "run_id": experiment_logger.run_id}

    # ------------------------------------------------------- Safety (new core)

    station_transport = getattr(safety_service, "transport", None)

    @app.get("/api/safety/status")
    async def safety_status() -> dict:
        return safety_service.status()

    @app.get("/api/safety/snapshot")
    async def safety_snapshot() -> dict:
        return safety_service.snapshot()

    @app.post("/api/safety/start")
    async def safety_start() -> dict:
        return await safety_service.start()

    @app.post("/api/safety/stop")
    async def safety_stop() -> dict:
        return await safety_service.stop()

    @app.get("/api/safety/alerts")
    async def safety_alerts() -> dict:
        alerts = safety_service.alerts
        return {"active": alerts.active(), "history": alerts.history(), "all": alerts.all()}

    @app.post("/api/safety/alerts/{alert_id}/ack")
    async def safety_alert_ack(alert_id: str, body: Optional[dict] = None) -> dict:
        result = await safety_service.acknowledge(alert_id, note=(body or {}).get("note", ""))
        return result

    @app.get("/api/safety/incidents")
    async def safety_incidents() -> dict:
        return {"incidents": safety_service.incidents.all()}

    @app.get("/api/safety/incidents/{incident_id}")
    async def safety_incident_detail(incident_id: str) -> dict:
        incident = safety_service.incidents.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        return {"incident": incident}

    @app.get("/api/safety/station")
    async def safety_station() -> dict:
        feed = []
        if station_transport is not None and hasattr(station_transport, "feed"):
            feed = station_transport.feed()
        return {"feed": feed, "count": len(feed)}

    @app.get("/api/safety/events")
    async def safety_events() -> dict:
        return {"events": safety_service.store.all()}

    @app.get("/api/safety/emergency")
    async def safety_emergency() -> dict:
        return {"status": safety_service.emergency.status(), "latest": safety_service.emergency.latest()}

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

    # ------------------------------------------------------------ Attendance

    @app.get("/api/attendance/status")
    async def attendance_status() -> dict:
        return attendance_monitor.status()

    @app.get("/api/attendance")
    async def attendance() -> dict:
        return attendance_monitor.latest()

    @app.get("/api/attendance/alerts")
    async def attendance_alerts() -> dict:
        alerts = attendance_monitor.alerts
        return {"active": alerts.active(), "history": alerts.history(), "all": alerts.all()}

    @app.post("/api/attendance/alerts/{alert_id}/ack")
    async def attendance_alert_ack(alert_id: str, body: Optional[dict] = None) -> dict:
        return await attendance_monitor.acknowledge(alert_id, note=(body or {}).get("note", ""))

    # ---------------------------------------------------------------- WebSocket

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            await websocket.send_json({"type": "state", "data": service.snapshot()})
            await websocket.send_json({"type": "safety", "data": safety_service.snapshot()})
            await websocket.send_json({"type": "experiment_engine", "data": state_engine.snapshot()})
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
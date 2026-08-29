"""BAS-AI FastAPI backend.

REST control plane + WebSocket event stream. The state machine is the only
authority on step validity; the simulated perception source feeds it the same
Detection shapes the future camera pipeline will.

Run:
    uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .experiment import load_active_experiment
from .log_store import LogStore
from .manager import ConnectionManager
from .schemas import ExperimentDef
from .service import ExperimentService
from .simulator import SimulatedPerception

logging.basicConfig(level=logging.INFO)


def create_app(
    experiment: Optional[ExperimentDef] = None,
    sim_script: Optional[list] = None,
) -> FastAPI:
    exp = experiment or load_active_experiment()
    manager = ConnectionManager()
    store = LogStore()
    service = ExperimentService(exp, manager, store)
    simulator = SimulatedPerception(sim_script)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await service.stop()

    app = FastAPI(title="BAS-AI Backend", version="0.1.0", lifespan=lifespan)
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

    # ------------------------------------------------------------------ REST

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "source": simulator.name,
            "experiment_id": exp.id,
            "clients": manager.count(),
        }

    @app.get("/api/experiment")
    async def get_experiment() -> dict:
        return {"experiment": exp.model_dump(), "state": service.snapshot()}

    @app.get("/api/experiment/status")
    async def get_status() -> dict:
        return service.snapshot()

    @app.post("/api/experiment/start")
    async def start() -> dict:
        return await service.start(simulator)

    @app.post("/api/experiment/stop")
    async def stop() -> dict:
        return await service.stop()

    @app.get("/api/logs")
    async def logs() -> dict:
        return {"events": store.all()}

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
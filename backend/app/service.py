"""Experiment service: orchestrates the session, simulator, log store and
WebSocket broadcasters. This is the seam where the simulator is replaced by
the real perception pipeline."""

import asyncio
import logging
from typing import Optional

from .log_store import LogStore
from .manager import ConnectionManager
from .schemas import Detection, ExperimentDef
from .simulator import SimulatedPerception
from .state_machine import ExperimentSession

logger = logging.getLogger("basai.service")


class ExperimentService:
    def __init__(self, experiment: ExperimentDef, manager: ConnectionManager, store: LogStore) -> None:
        self.experiment = experiment
        self.manager = manager
        self.store = store
        self.session = ExperimentSession(experiment)
        self.task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def snapshot(self) -> dict:
        return self.session.snapshot()

    async def _publish(self, events) -> None:
        for event in events:
            payload = event.model_dump(by_alias=True)
            self.store.append(payload)
            await self.manager.broadcast({"type": "event", "data": payload})
        await self.manager.broadcast({"type": "state", "data": self.snapshot()})

    async def start(self, simulator: SimulatedPerception) -> dict:
        async with self._lock:
            if self.task and not self.task.done():
                return self.snapshot()
            events = self.session.start()
            await self._publish(events)

            async def run() -> None:
                try:
                    async for detection in simulator.detections():
                        payload = detection.model_dump()
                        await self.manager.broadcast({"type": "detection", "data": payload})
                        await self._publish(self.session.on_detection(detection))
                        if self.session.status == "COMPLETED":
                            break
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.exception("Simulator task failed")

            self.task = asyncio.create_task(run())
            return self.snapshot()

    async def stop(self) -> dict:
        async with self._lock:
            if self.task and not self.task.done():
                self.task.cancel()
            self.task = None
            if self.session.status == "RUNNING":
                await self._publish(self.session.stop())
            return self.snapshot()
"""WebSocket connection management and broadcast helper."""

import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger("basai.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._active.discard(websocket)

    def count(self) -> int:
        return len(self._active)

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._active):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - connection may have dropped
                dead.append(ws)
        for ws in dead:
            self._active.discard(ws)
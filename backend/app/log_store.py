"""In-memory bounded event log. Swappable for SQLite persistence in a later
phase without changing the service layer."""

from typing import List

from .config import LOG_LIMIT


class LogStore:
    def __init__(self, limit: int = LOG_LIMIT) -> None:
        self._limit = limit
        self._events: List[dict] = []

    def append(self, event: dict) -> None:
        self._events.append(event)
        if len(self._events) > self._limit:
            del self._events[: len(self._events) - self._limit]

    def all(self) -> List[dict]:
        return list(self._events)

    def clear(self) -> None:
        self._events = []
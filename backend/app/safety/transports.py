"""Alert / evidence delivery transports.

Nothing here touches a real spacecraft or Earth link — that is the point. The
prototype ships with a local Mission-Control panel feed and a file transport;
a real comms layer plugs in behind the same interfaces later without touching
the safety logic.

    AlertTransport
        |- LocalMissionControlTransport   in-process panel feed (REST/WS)
        |- FileTransport                  appends station alerts to disk
        `- FutureSpaceStationTransport    placeholder for real comms

For Earth escalation the same idea applies: the EvidenceEscalationClient
interface receives a fully-built package; the prototype implementation only
*writes it locally* and reports ``EARTH_ESCALATION_PACKAGE_READY`` — it never
claims transmission.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class StationAlert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    incident_id: Optional[str] = None
    severity: str
    event_type: str
    title: str
    message: str
    confidence: float = 0.0
    timestamp: int = 0
    source: str = "safe-monitor"


class AlertTransport(ABC):
    """Delivers a station-focused alert. Swapped per environment."""

    @abstractmethod
    def send_station_alert(self, alert: StationAlert) -> dict:
        raise NotImplementedError

    @abstractmethod
    def send_escalation_package(self, incident_id: str, package_dir: Path) -> dict:
        raise NotImplementedError


class LocalMissionControlTransport(AlertTransport):
    """In-memory "Mission Control / Space Station" panel feed. The dashboard
    polls/streams it looking exactly like a station console — but nothing is
    actually transmitted anywhere."""

    name = "local-mission-control"

    def __init__(self, limit: int = 100) -> None:
        self._feed: List[StationAlert] = []
        self.limit = limit

    def reset(self) -> None:
        self._feed.clear()

    def feed(self) -> List[StationAlert]:
        return list(self._feed)

    def send_station_alert(self, alert: StationAlert) -> dict:
        self._feed.append(alert)
        if len(self._feed) > self.limit:
            del self._feed[: len(self._feed) - self.limit]
        return {"transport": self.name, "delivered": True, "id": alert.id}

    def send_escalation_package(self, incident_id: str, package_dir: Path) -> dict:
        return {"transport": self.name, "package": str(package_dir), "sent": False, "staged": True}


class FileTransport(AlertTransport):
    """Persists station alerts + escalation packages as local files.
    Still local-only: files on disk are the extent of 'delivery'."""

    name = "file"

    def __init__(self, root: Path, alerts_file: str = "station_alerts.jsonl") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.alerts_path = self.root / alerts_file

    def send_station_alert(self, alert: StationAlert) -> dict:
        line = json.dumps(alert.model_dump(by_alias=True))
        with self.alerts_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return {"transport": self.name, "delivered": True, "file": str(self.alerts_path), "id": alert.id}

    def send_escalation_package(self, incident_id: str, package_dir: Path) -> dict:
        target = self.root / "escalation" / incident_id
        target.mkdir(parents=True, exist_ok=True)
        return {"transport": self.name, "staged_to": str(target), "sent": False}


class FutureSpaceStationTransport(AlertTransport):
    """Placeholder seam for a real spacecraft/ground link. Sending raises so
    nobody can accidentally 'deliver' anything with an unimplemented backend."""

    name = "future-space-station"

    def send_station_alert(self, alert: StationAlert) -> dict:
        raise NotImplementedError("Real station comms are not part of this prototype.")

    def send_escalation_package(self, incident_id: str, package_dir: Path) -> dict:
        raise NotImplementedError("Real Earth comms are not part of this prototype.")


def new_station_alert_id(timestamp: int) -> str:
    return f"station-{timestamp}-{int(time.time() * 1_000_000) % 100000}"
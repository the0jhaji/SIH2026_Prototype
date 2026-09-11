"""Incident records, evidence storage and Earth-escalation packaging.

An incident is created when a confirmed CRITICAL or EMERGENCY event occurs.
Evidence (current frame + detection/model metadata) is captured once per
incident and stored under::

    data/incidents/<incident_id>/
        event.json            incident record (canonical, reloaded at boot)
        frame.jpg             evidence frame (when the camera was running)
        metadata.json         detector/model/detection snapshot at event time
        escalation.json       Earth-escalation package (local-only)

Earth escalation is staged LOCALLY and reported as ``EARTH_ESCALATION_PACKAGE
_READY``; no transmission is claimed. The escalation transport interface is
where real comms plug in later.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_incident_id(timestamp: int) -> str:
    suffix = f"{int(time.time() * 1_000_000) % 1_000_000}"
    return f"INC-{timestamp}-{suffix}"


class EvidenceRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str  # frame | metadata | package
    path: str
    captured_at: int


class EscalationStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str = "DISABLED"  # DISABLED | READY | FAILED
    criteria: str = ""
    path: str = ""
    created_at: Optional[int] = None


class Incident(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    incident_id: str
    severity: str  # WARNING | CRITICAL | EMERGENCY
    event_type: str
    timestamp: int
    confidence: float = 0.0
    description: str = ""
    recommended_action: str = ""
    trigger_key: str = ""
    state: str = "OPEN"  # OPEN | ACKNOWLEDGED | RESOLVED
    mission_state: str = "NORMAL"
    source: str = "safety-monitor"
    evidence: List[EvidenceRef] = Field(default_factory=list)
    assessment: Optional[dict] = None
    escalation: EscalationStatus = Field(default_factory=EscalationStatus)

    def metadata(self) -> dict:
        return self.model_dump(by_alias=True)


class IncidentLog:
    """In-memory incident index persisted to ``data/incidents/``. Open incidents
    survive restarts by reloading each ``event.json`` on construction."""

    def __init__(self, root: Optional[Path | str] = None, model_version: str = "unknown") -> None:
        self.root = Path(root) if root else None
        self.model_version = model_version
        self._incidents: Dict[str, Incident] = {}
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _dir_for(self, incident_id: str) -> Path:
        assert self.root is not None, "IncidentLog needs a root to persist evidence"
        path = self.root / incident_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load_existing(self) -> None:
        assert self.root is not None
        for event_file in sorted(self.root.glob("*/event.json")):
            try:
                raw = json.loads(event_file.read_text(encoding="utf-8"))
                incident = Incident(**raw)
                self._incidents[incident.incident_id] = incident
            except Exception:  # noqa: BLE001 - never crash boot over one file
                continue

    # ---------------------------------------------------------------- access

    def all(self) -> List[Incident]:
        return sorted(self._incidents.values(), key=lambda i: -i.timestamp)

    def get(self, incident_id: str) -> Optional[Incident]:
        return self._incidents.get(incident_id)

    def open_by_key(self, key: str) -> Optional[Incident]:
        for incident in self._incidents.values():
            if incident.trigger_key == key and incident.state in {"OPEN", "ACKNOWLEDGED"}:
                return incident
        return None

    def incidents(self, limit: int = 100) -> List[Incident]:
        return self.all()[:limit]

    # --------------------------------------------------------------- lifecycle

    def create(
        self,
        *,
        severity: str,
        event_type: str,
        confidence: float,
        description: str,
        recommended_action: str,
        trigger_key: str,
        mission_state: str,
        assessment: Optional[dict] = None,
        timestamp: Optional[int] = None,
    ) -> Incident:
        timestamp = timestamp if timestamp is not None else _now_ms()
        incident_id = _new_incident_id(timestamp)
        incident = Incident(
            incident_id=incident_id,
            severity=severity,
            event_type=event_type,
            timestamp=timestamp,
            confidence=round(confidence, 4),
            description=description,
            recommended_action=recommended_action,
            trigger_key=trigger_key,
            state="OPEN",
            mission_state=mission_state,
            assessment=assessment,
        )
        self._incidents[incident.incident_id] = incident
        self._persist(incident)
        return incident

    def acknowledge(self, incident_id: str, note: str = "") -> Optional[Incident]:
        incident = self._incidents.get(incident_id)
        if incident is None or incident.state == "RESOLVED":
            return None
        incident.state = "ACKNOWLEDGED"
        if note:
            incident.description = (incident.description + f" [ack note: {note}]").strip()
        self._persist(incident)
        return incident

    def resolve(self, incident_id: str) -> Optional[Incident]:
        incident = self._incidents.get(incident_id)
        if incident is None:
            return None
        if incident.state != "RESOLVED":
            incident.state = "RESOLVED"
            self._persist(incident)
        return incident

    def resolve_by_key(self, key: str) -> Optional[Incident]:
        incident = self.open_by_key(key)
        return self.resolve(incident.incident_id) if incident else None

    def _persist(self, incident: Incident) -> None:
        if self.root is None:
            return
        directory = self._dir_for(incident.incident_id)
        (directory / "event.json").write_text(
            json.dumps(incident.model_dump(by_alias=True), indent=2),
            encoding="utf-8",
        )

    # ----------------------------------------------------------------- evidence

    def save_frame(self, incident_id: str, jpeg_bytes: bytes, frame_id: int, timestamp: int) -> EvidenceRef:
        """Store the evidence frame JPEG next to the incident. Returns the ref."""
        directory = self._dir_for(incident_id)
        path = directory / f"frame_{timestamp}.jpg"
        path.write_bytes(jpeg_bytes)
        ref = EvidenceRef(type="frame", path=str(path), captured_at=timestamp)
        incident = self._incidents[incident_id]
        incident.evidence.append(ref)
        self._persist(incident)
        return ref

    def save_metadata(self, incident_id: str, metadata: dict, timestamp: int) -> EvidenceRef:
        directory = self._dir_for(incident_id)
        path = directory / "metadata.json"
        payload = {"captured_at": timestamp, **metadata}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        ref = EvidenceRef(type="metadata", path=str(path), captured_at=timestamp)
        incident = self._incidents[incident_id]
        incident.evidence.append(ref)
        self._persist(incident)
        return ref

    # --------------------------------------------------------------- escalation

    def stage_escalation(self, incident_id: str, criteria: str, package: dict) -> EscalationStatus:
        """Build the local Earth-escalation package. This only *stages* files;
        ``EscalationStatus.status`` reads ``READY`` — never "sent"."""
        incident = self._incidents[incident_id]
        directory = self._dir_for(incident_id)
        path = directory / "escalation.json"
        package["_status"] = "EARTH_ESCALATION_PACKAGE_READY"
        package["_note"] = "Locally staged for manual hand-off. No real transmission interface exists in this prototype."
        path.write_text(json.dumps(package, indent=2), encoding="utf-8")
        status = EscalationStatus(
            status="READY",
            criteria=criteria,
            path=str(path),
            created_at=_now_ms(),
        )
        incident.escalation = status
        self._persist(incident)
        return status
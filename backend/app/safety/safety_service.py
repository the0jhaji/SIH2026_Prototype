"""SafetyService: orchestrates the monitoring loop.

Pulls the latest object detections on its own async tick, runs the hazard
engine (temporal confirmation + microgravity risk), feeds the safety monitor,
reconciles alerts, creates incidents for confirmed CRITICAL/EMERGENCY events,
captures evidence frames, stages Earth-escalation packages, delivers station
alerts to the transports, and broadcasts everything over WebSocket.

The camera/detector layers are untouched: this service only consumes
``detection_service.latest()`` / ``.status()`` and ``camera.latest_jpeg()``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Optional

logger = logging.getLogger("astraai.safety")

from .. import config
from .alert_manager import Alert, AlertManager, AlertSignal
from .emergency import EmergencyManager, EmergencySignal
from .hazard_engine import HazardEngine, SceneAssessment
from .incidents import Incident, IncidentLog
from .monitor import SafetyMonitor
from .transports import AlertTransport, StationAlert, new_station_alert_id

_ALERT_LEVEL_BY_RISK = {"CRITICAL": "CRITICAL", "WARNING": "WARNING", "CAUTION": "CAUTION", "SAFE": "INFO"}


class SafetyService:
    def __init__(
        self,
        *,
        detection_service,
        camera_manager,
        manager,
        store,
        engine: HazardEngine,
        emergency: EmergencyManager,
        monitor: SafetyMonitor,
        alerts: AlertManager,
        incidents: IncidentLog,
        transport: AlertTransport,
        poll_ms: int = 500,
        escalate_enabled: bool = False,
        escalate_min_level: str = "CRITICAL",
        model_version: str = "unknown",
    ) -> None:
        self.detection_service = detection_service
        self.camera_manager = camera_manager
        self.manager = manager
        self.store = store
        self.engine = engine
        self.emergency = emergency
        self.monitor = monitor
        self.alerts = alerts
        self.incidents = incidents
        self.transport = transport
        self.poll_ms = max(10, poll_ms)
        self.escalate_enabled = escalate_enabled
        self.escalate_min_level = escalate_min_level
        self.model_version = model_version
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._monitoring = False
        self._ev_seq = 0
        self._tick = 0
        self._scene: Optional[SceneAssessment] = None
        self._last_payload: Optional[dict] = None
        self._last_emergency: Optional[EmergencySignal] = None
        self._last_snapshot: Optional[dict] = None

    # ----------------------------------------------------------------- events

    def _log(self, kind: str, message: str, severity: str = "info", level: str | None = None, **extra: object) -> dict:
        self._ev_seq += 1
        event = {
            "seq": self._ev_seq,
            "ts": int(time.time() * 1000),
            "kind": kind,
            "severity": severity,
            "message": message,
            "level": level,
            **extra,
        }
        self.store.append(event)
        return event

    async def _broadcast(self, event: dict) -> None:
        await self.manager.broadcast({"type": "safety_event", "data": event})

    async def _publish_event(self, event: dict) -> None:
        await self._broadcast(event)

    async def _publish_snapshot(self) -> None:
        snapshot = self.snapshot()
        self._last_snapshot = snapshot
        await self.manager.broadcast({"type": "safety", "data": snapshot})

    # ----------------------------------------------------------------- control

    def is_monitoring(self) -> bool:
        return self._monitoring

    async def start(self) -> dict:
        async with self._lock:
            if self._monitoring:
                return self.snapshot()
            self._monitoring = True
            self.engine.reset()
            self.emergency.reset()
            self.monitor.reset()
            for ev in self.monitor.start():
                await self._publish_event(ev)
            self._task = asyncio.create_task(self._loop())
            logger.info("Safety monitoring started")
            await self._publish_snapshot()
            return self.snapshot()

    async def stop(self) -> dict:
        async with self._lock:
            if not self._monitoring:
                return self.snapshot()
            self._monitoring = False
            if self._task is not None:
                self._task.cancel()
                self._task = None
            for ev in self.monitor.stop():
                await self._publish_event(ev)
            logger.info("Safety monitoring stopped")
            await self._publish_snapshot()
            return self.snapshot()

    async def acknowledge(self, alert_id: str, note: str = "") -> dict:
        alert = self.alerts.acknowledge(alert_id, note=note)
        if alert is None:
            return {"found": False}
        for ev in self.monitor.acknowledge(note=note):
            await self._publish_event(ev)
        incident = None
        if alert.incident_id:
            incident = self.incidents.acknowledge(alert.incident_id, note)
            if incident is not None:
                await self._publish_event(
                    self._log(
                        "INCIDENT_ACKNOWLEDGED",
                        f"Incident {incident.incident_id} acknowledged",
                        severity="info",
                        level=incident.severity,
                        incident_id=incident.incident_id,
                    )
                )
        await self._publish_snapshot()
        return {"found": True, "alert": alert, "incident": incident}

    # ------------------------------------------------------------------ loop

    async def _loop(self) -> None:
        while self._monitoring:
            await asyncio.sleep(self.poll_ms / 1000.0)
            try:
                await self.step()
            except Exception as exc:  # noqa: BLE001 - the monitor never dies
                logger.exception("Safety monitor step failed")
                await self._broadcast(self._log("SAFETY_ERROR", f"Monitor step failed: {exc}", severity="error"))

    async def step(self) -> None:
        self._tick += 1
        now = int(time.time() * 1000)
        payload = self.detection_service.latest()
        scene = self.engine.assess(payload, now)
        emergency = self.emergency.update(payload, scene, now)
        self._scene = scene
        self._last_payload = payload
        self._last_emergency = emergency

        events: List[dict] = []
        for ev in self.monitor.update(scene, emergency, now):
            events.append(self._log(**self._ev_kwargs(ev)))

        alert_events: List[dict] = []
        signals = self._alert_signals(scene, emergency)
        handled_ids: set[str] = set()
        for alert in self.alerts.update(signals, now):
            if alert.id in handled_ids:
                continue
            handled_ids.add(alert.id)
            if alert.resolved:
                kind, severity, message = "ALERT_RESOLVED", "info", f"Alert resolved: {alert.title}"
                if alert.incident_id:
                    self.incidents.resolve(alert.incident_id)
            elif alert.acknowledged:
                kind, severity, message = "ALERT_ACKNOWLEDGED", "info", f"Alert acknowledged: {alert.title}"
            elif self._is_new_alert(alert):
                kind, severity, message = "ALERT_RAISED", "warn", f"{alert.level} — {alert.message}"
            else:
                kind, severity, message = "ALERT_ESCALATED", "warn", f"{alert.level} — {alert.message}"
            alert_events.append(
                self._log(kind, message, severity=severity, level=alert.level, alert_id=alert.id, object=alert.object)
            )

        incident_events = await self._incident_processing(now)

        for ev in events + alert_events + incident_events:
            await self._broadcast(ev)
        await self._publish_snapshot()

    def _ev_kwargs(self, ev: dict) -> dict:
        extra = {k: v for k, v in ev.items() if k not in {"ts"}}
        return extra

    def _is_new_alert(self, alert: Alert) -> bool:
        return alert.created_at == alert.updated_at

    # ------------------------------------------------------------ signal build

    def _alert_signals(self, scene: SceneAssessment, emergency: Optional[EmergencySignal]) -> List[AlertSignal]:
        signals: List[AlertSignal] = []
        for a in scene.hazards:
            if not a.confirmed:
                continue
            level = _ALERT_LEVEL_BY_RISK.get(a.risk_level, "INFO")
            if level == "INFO":
                continue
            signals.append(
                AlertSignal(
                    key=f"hazard:{a.object}:{a.hazard_type or 'object'}",
                    level=level,
                    title=f"{a.object.replace('_', ' ').title()} hazard",
                    message=(
                        f"{a.object} ({a.hazard_type or 'untyped'}) — risk {a.risk_level} "
                        f"{a.risk_score:.0%}"
                        + (" near astronaut" if a.near_astronaut else "")
                    ),
                    risk_score=a.risk_score,
                    confidence=a.confidence,
                    object=a.object,
                    hazard_type=a.hazard_type,
                    recommended_action=a.recommended_action,
                    event_type="HAZARD_DETECTED",
                )
            )
        if emergency is not None and emergency.confirmed:
            signals.append(
                AlertSignal(
                    key=f"emergency:{emergency.event_type}",
                    level="EMERGENCY",
                    title="Possible astronaut emergency",
                    message=f"{emergency.event_type} — {emergency.description}",
                    risk_score=1.0,
                    confidence=emergency.confidence,
                    object="person",
                    hazard_type=emergency.event_type,
                    recommended_action=emergency.recommended_action,
                    event_type=emergency.event_type,
                )
            )
        return signals

    # ----------------------------------------------------------- incidents

    async def _incident_processing(self, now: int) -> List[dict]:
        events: List[dict] = []
        scene = self._scene
        if scene is None or scene.stale:
            return events
        present_keys: set[str] = set()

        for a in scene.hazards:
            if not a.confirmed or a.risk_level not in {"CRITICAL", "WARNING"}:
                continue
            if a.risk_level == "WARNING" and not a.near_astronaut:
                continue
            key = f"hazard:{a.object}:{a.hazard_type or 'object'}"
            present_keys.add(key)
            if self.incidents.open_by_key(key) is not None:
                continue
            severity = "WARNING" if a.risk_level == "WARNING" else "CRITICAL"
            incident = self.incidents.create(
                severity=severity,
                event_type="HAZARD_DETECTED",
                confidence=a.confidence,
                description=(
                    f"Confirmed {a.risk_level} hazard: {a.object}"
                    + (f" ({a.hazard_type})" if a.hazard_type else "")
                    + (" in the astronaut's vicinity" if a.near_astronaut else "")
                ),
                recommended_action=a.recommended_action,
                trigger_key=key,
                mission_state=self.monitor.state,
                assessment=a.model_dump(by_alias=True),
            )
            events += await self._finalize_incident(incident, now)

        emergency = self._last_emergency
        if emergency is not None and emergency.confirmed:
            key = f"emergency:{emergency.event_type}"
            present_keys.add(key)
            if self.incidents.open_by_key(key) is None:
                incident = self.incidents.create(
                    severity="EMERGENCY",
                    event_type=emergency.event_type,
                    confidence=emergency.confidence,
                    description=emergency.description,
                    recommended_action=emergency.recommended_action,
                    trigger_key=key,
                    mission_state=self.monitor.state,
                )
                events += await self._finalize_incident(incident, now)

        for incident in self.incidents.all():
            if incident.state in {"OPEN", "ACKNOWLEDGED"} and incident.trigger_key.startswith("hazard:"):
                if incident.trigger_key not in present_keys:
                    self.incidents.resolve(incident.incident_id)
                    events.append(
                        self._log(
                            "INCIDENT_RESOLVED",
                            f"Incident {incident.incident_id} resolved (hazard cleared)",
                            severity="info",
                            level=incident.severity,
                            incident_id=incident.incident_id,
                        )
                    )
        return events

    async def _finalize_incident(self, incident: Incident, now: int) -> List[dict]:
        events: List[dict] = []
        events.append(
            self._log(
                "INCIDENT_CREATED",
                f"Incident {incident.incident_id} ({incident.severity}) — {incident.description}",
                severity="warn" if incident.severity != "EMERGENCY" else "error",
                level=incident.severity,
                incident_id=incident.incident_id,
                event_type=incident.event_type,
            )
        )
        # Evidence: current camera frame (if running) + detection/model metadata.
        captured = self._capture_evidence(incident, now)
        events.extend(captured)

        # Station alert for the mission-control / space-station panel.
        await self._station_alert(incident)

        # Earth escalation when criteria are met (local package only).
        if self.escalate_enabled and _severity_index(incident.severity) >= _severity_index(self.escalate_min_level):
            events.append(await self._stage_escalation(incident))
        return events

    def _capture_evidence(self, incident: Incident, now: int) -> List[dict]:
        events: List[dict] = []
        latest = self.camera_manager.latest_jpeg()
        detection_status = self.detection_service.status()
        payload = self._last_payload or {}
        metadata = {
            "incident_id": incident.incident_id,
            "model_version": self.model_version,
            "detector": detection_status.get("detector"),
            "model_path": detection_status.get("modelPath"),
            "classes": detection_status.get("classes"),
            "environment_mode": self.engine.environment,
            "mission_state": self.monitor.state,
            "frame_width": payload.get("frameWidth"),
            "frame_height": payload.get("frameHeight"),
            "detections": payload.get("detections") or [],
            "assessments": [a.model_dump(by_alias=True) for a in (self._scene.assessments if self._scene else [])],
        }
        self.incidents.save_metadata(incident.incident_id, metadata, now)
        events.append(
            self._log(
                "EVIDENCE_CAPTURED",
                f"Evidence metadata saved for {incident.incident_id}",
                severity="info",
                level=incident.severity,
                incident_id=incident.incident_id,
            )
        )
        if latest is not None:
            frame_id, jpeg = latest
            self.incidents.save_frame(incident.incident_id, jpeg, frame_id, now)
            events.append(
                self._log(
                    "EVIDENCE_CAPTURED",
                    f"Evidence frame saved for {incident.incident_id}",
                    severity="info",
                    level=incident.severity,
                    incident_id=incident.incident_id,
                )
            )
        else:
            events.append(
                self._log(
                    "EVIDENCE_CAPTURED",
                    f"No evidence frame for {incident.incident_id} (camera not streaming)",
                    severity="info",
                    level=incident.severity,
                    incident_id=incident.incident_id,
                )
            )
        return events

    async def _station_alert(self, incident: Incident) -> None:
        if self.transport is None:
            return
        try:
            self.transport.send_station_alert(
                StationAlert(
                    id=new_station_alert_id(incident.timestamp),
                    incident_id=incident.incident_id,
                    severity=incident.severity,
                    event_type=incident.event_type,
                    title=f"{incident.severity} — {incident.event_type}",
                    message=incident.description,
                    confidence=incident.confidence,
                    timestamp=incident.timestamp,
                )
            )
        except NotImplementedError:
            return
        except Exception as exc:  # noqa: BLE001 - station feed never breaks the loop
            logger.warning("Station alert delivery failed: %s", exc)

    async def _stage_escalation(self, incident: Incident) -> dict:
        scene = self._scene
        package = {
            "incident_id": incident.incident_id,
            "timestamp": incident.timestamp,
            "severity": incident.severity,
            "event_type": incident.event_type,
            "description": incident.description,
            "confidence": incident.confidence,
            "risk_level": incident.severity,
            "risk_score": (incident.assessment or {}).get("risk_score"),
            "recommended_action": incident.recommended_action,
            "detected_objects": [a.object for a in (scene.assessments if scene else [])],
            "evidence": [ref.model_dump(by_alias=True) for ref in incident.evidence],
            "system_version": self.model_version,
            "environment_mode": self.engine.environment,
            "mission_state": self.monitor.state,
            "rolling_frames": [],
            "rolling_note": "Rolling pre/post-event frame buffer is not implemented in the prototype; a single frame is staged.",
        }
        criteria = f"severity >= {self.escalate_min_level}"
        self.incidents.stage_escalation(incident.incident_id, criteria, package)
        event = self._log(
            "EARTH_ESCALATION_READY",
            f"EARTH ESCALATION PACKAGE READY for {incident.incident_id} (locally staged, not transmitted)"
            if self._local_escalation()
            else f"Escalation staged for {incident.incident_id}",
            severity="warn",
            level=incident.severity,
            incident_id=incident.incident_id,
        )
        return event

    def _local_escalation(self) -> bool:
        transport_name = getattr(getattr(self, "transport", None), "name", "")
        return transport_name != "future-space-station"

    # ----------------------------------------------------------------- status

    def status(self) -> dict:
        detection_status = self.detection_service.status()
        emergency_status = self.emergency.status()
        emergencies = [i for i in self.incidents.all() if i.severity == "EMERGENCY"]
        escalations = [i for i in self.incidents.all() if i.escalation.status == "READY"]
        return {
            "monitoring": self._monitoring,
            "environment_mode": self.engine.environment,
            "mission_state": self.monitor.state,
            "overall_risk_level": (self._scene.overall_risk_level if self._scene else "SAFE"),
            "overall_risk_score": (self._scene.overall_risk_score if self._scene else 0.0),
            "feed_stale": bool(self._scene and self._scene.stale),
            "detector": detection_status.get("detector"),
            "detector_error": detection_status.get("error"),
            "model_version": self.model_version,
            "tick": self._tick,
            "alerts_active": len(self.alerts.active()),
            "incidents_open": len([i for i in self.incidents.all() if i.state in {"OPEN", "ACKNOWLEDGED"}]),
            "emergency": emergency_status,
            "escalations_ready": len(escalations),
            "emergency_incidents": len(emergencies),
        }

    def snapshot(self) -> dict:
        scene = self._scene
        emergency = self._last_emergency
        return {
            "monitoring": self._monitoring,
            "mission_state": self.monitor.state,
            "environment_mode": self.engine.environment,
            "overall_risk_level": scene.overall_risk_level if scene else "SAFE",
            "overall_risk_score": scene.overall_risk_score if scene else 0.0,
            "feed_stale": bool(scene and scene.stale),
            "assessments": [a.model_dump(by_alias=True) for a in (scene.assessments if scene else [])],
            "top_hazard": scene.top_hazard.model_dump(by_alias=True) if scene and scene.top_hazard else None,
            "astronaut_in_view": bool(scene and scene.astronaut_in_view),
            "astronaut_box": scene.astronaut_box if scene else None,
            "unclassified": scene.unclassified if scene else [],
            "emergency": emergency.model_dump(by_alias=True) if emergency else None,
            "monitor": self.monitor.snapshot(),
            "detector": self.detection_service.status().get("detector"),
            "detector_error": self.detection_service.status().get("error"),
            "model_version": self.model_version,
            "timestamp": int(time.time() * 1000),
        }

    def close(self) -> None:
        if self._task is not None:
            self._monitoring = False
            self._task.cancel()
            self._task = None


def _severity_index(severity: str) -> int:
    return {"SAFE": 0, "INFO": 0, "CAUTION": 0, "WARNING": 1, "CRITICAL": 2, "EMERGENCY": 3}.get(severity, 0)
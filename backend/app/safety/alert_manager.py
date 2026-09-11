"""Centralized alert manager.

Alert levels: INFO / CAUTION / WARNING / CRITICAL / EMERGENCY.

Rules (the "do NOT spam the astronaut every frame" contract):
  * A signal only raises an alert when it reaches CAUTION or above.
  * Alerts are de-duplicated by a root-cause ``key`` (object + hazard type).
  * A resolved alert is not re-raised within its cooldown window.
  * While an alert is active, an increasing risk level ESLATES the same alert
    instead of opening a duplicate.
  * Alerts whose root cause disappears are RESOLVED (auto) — resolution only
    ever comes from fresh assessment data, never from a dead feed.
  * Alerts can be acknowledged; acknowledging escalations is allowed.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

AlertLevel = str  # INFO | CAUTION | WARNING | CRITICAL | EMERGENCY

_LEVEL_INDEX = {"INFO": 0, "CAUTION": 1, "WARNING": 2, "CRITICAL": 3, "EMERGENCY": 4}


class AlertSignal(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str
    level: AlertLevel
    title: str
    message: str
    risk_score: float = 0.0
    confidence: float = 0.0
    object: Optional[str] = None
    hazard_type: Optional[str] = None
    recommended_action: str = ""
    event_type: str = "HAZARD_DETECTED"


class Alert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    key: str
    level: AlertLevel = "INFO"
    title: str = ""
    message: str = ""
    event_type: str = "HAZARD_DETECTED"
    risk_score: float = 0.0
    confidence: float = 0.0
    object: Optional[str] = None
    hazard_type: Optional[str] = None
    recommended_action: str = ""
    created_at: int = 0
    updated_at: int = 0
    acknowledged: bool = False
    acked_at: Optional[int] = None
    ack_note: str = ""
    resolved: bool = False
    resolved_at: Optional[int] = None
    incident_id: Optional[str] = None


def new_alert_id(now: int) -> str:
    return f"alert-{now}-{int(time.time() * 1_000_000) % 100000}"


class AlertManager:
    def __init__(
        self,
        *,
        cooldown_ms: int = 15000,
        history_limit: int = 200,
    ) -> None:
        self.cooldown_ms = cooldown_ms
        self.history_limit = history_limit
        self._active: Dict[str, Alert] = {}
        self._resolved_at: Dict[str, int] = {}
        self._history: List[Alert] = []
        self._seq = 0

    # -------------------------------------------------------------- lifecycle

    def reset(self) -> None:
        self._active.clear()
        self._resolved_at.clear()
        self._history.clear()

    def active(self, now: Optional[int] = None) -> List[Alert]:
        del now
        return list(self._active.values())

    def history(self) -> List[Alert]:
        return list(self._history)

    def all(self) -> List[Alert]:
        """Active first (newest active first), then recent resolved history."""
        active = sorted(self._active.values(), key=lambda a: -a.updated_at)
        resolved = sorted(
            [a for a in self._resolved_at.keys() if a not in self._active],
            key=lambda k: -self._resolved_at[k],
        )
        resolved_alerts: List[Alert] = []
        seen: set[str] = set()
        for a in self._history:
            if a.id in seen:
                continue
            seen.add(a.id)
            if a.resolved:
                resolved_alerts.append(a)
        return active + resolved_alerts

    def get(self, alert_id: str) -> Optional[Alert]:
        for a in self.all():
            if a.id == alert_id:
                return a
        return None

    # ---------------------------------------------------------------- update

    def update(self, signals: List[AlertSignal], now: int) -> List[Alert]:
        """Reconcile active alerts against the current signal set. Returns the
        snapshot of alerts affected this cycle (raised/escalated/resolved) so
        the orchestrator can log + broadcast per-alert events."""
        touched: List[Alert] = []
        seen: set[str] = set()

        ordered = sorted(signals, key=lambda s: _LEVEL_INDEX[s.level], reverse=True)
        for sig in ordered:
            seen.add(sig.key)
            existing = self._active.get(sig.key)
            if existing is not None:
                escalated = _LEVEL_INDEX[sig.level] > _LEVEL_INDEX[existing.level]
                if escalated:
                    existing.level = sig.level
                    existing.title = sig.title
                    existing.message = sig.message
                    existing.event_type = sig.event_type
                existing.risk_score = sig.risk_score
                existing.confidence = sig.confidence
                existing.updated_at = now
                # Only report real changes so a persistent hazard does not
                # spam ALERT_ESCALATED on every tick.
                if escalated:
                    touched.append(existing)
                continue
            if self._is_dedupe_cooldown(sig.key, now):
                continue
            alert = Alert(
                id=new_alert_id(now),
                key=sig.key,
                level=sig.level,
                title=sig.title,
                message=sig.message,
                event_type=sig.event_type,
                risk_score=sig.risk_score,
                confidence=sig.confidence,
                object=sig.object,
                hazard_type=sig.hazard_type,
                recommended_action=sig.recommended_action,
                created_at=now,
                updated_at=now,
            )
            self._active[sig.key] = alert
            self._history.append(alert)
            touched.append(alert)

        for key in list(self._active):
            if key not in seen:
                alert = self._active.pop(key)
                alert.resolved = True
                alert.resolved_at = now
                self._resolved_at[key] = now
                touched.append(alert)
            else:
                self._resolved_at.pop(key, None)

        self._trim_history()
        return touched

    def _is_dedupe_cooldown(self, key: str, now: int) -> bool:
        resolved_at = self._resolved_at.get(key)
        return resolved_at is not None and (now - resolved_at) < self.cooldown_ms

    def _trim_history(self) -> None:
        if len(self._history) > self.history_limit:
            del self._history[: len(self._history) - self.history_limit]

    # ---------------------------------------------------------- interactions

    def acknowledge(self, alert_id: str, note: str = "", now: Optional[int] = None) -> Optional[Alert]:
        """Acknowledge an active alert. Acknowledging is allowed even for
        escalated alerts; the operator takes responsibility for the hazard."""
        now = now if now is not None else int(time.time() * 1000)
        for alert in self._active.values():
            if alert.id == alert_id:
                if not alert.acknowledged:
                    alert.acknowledged = True
                    alert.acked_at = now
                    alert.ack_note = note
                    alert.updated_at = now
                return alert
        return None
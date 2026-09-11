"""Experiment state engine — rich lifecycle + temporal confirmation.

Wraps the existing ``ExperimentSession`` (sequence validation) and adds:

* richer status enum (NOT_STARTED → RUNNING → … → COMPLETED)
* temporal confirmation: an activity must persist for several consecutive
  frames before it is promoted from CANDIDATE → CONFIRMED
* voice alert integration
* JSONL structured logging
* next-step suggestion tracking

This module never touches the camera or the detector directly — it
consumes ``Detection`` objects from the perception layer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from .experiment import expected_step, step_for_activity
from .experiment_log import ExperimentLogger
from .schemas import Detection, ExperimentDef, ExpEvent, StepDef
from .state_machine import ExperimentSession
from .voice_alert import VoiceAlertService

logger = logging.getLogger("astraai.experiment_state")

# ── explicit states ──────────────────────────────────────────────────────────

NOT_STARTED = "NOT_STARTED"
RUNNING = "RUNNING"
WAITING_FOR_STEP = "WAITING_FOR_STEP"
STEP_CANDIDATE = "STEP_CANDIDATE"
STEP_CONFIRMED = "STEP_CONFIRMED"
SEQUENCE_VIOLATION = "SEQUENCE_VIOLATION"
UNCERTAIN = "UNCERTAIN"
COMPLETED = "COMPLETED"
PAUSED = "PAUSED"
ABORTED = "ABORTED"

# ── configurable thresholds (env-overridable) ────────────────────────────────

import os


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, str(default)))


CONFIRM_FRAMES = _env_int("ACTIVITY_CONFIRM_FRAMES", 3)
MIN_CONFIDENCE = _env_float("ACTIVITY_MIN_CONFIDENCE", 0.5)
CONFIRM_WINDOW_MS = _env_int("ACTIVITY_CONFIRM_WINDOW_MS", 2000)


class ExperimentStateEngine:
    """Stateful experiment supervisor.

    Parameters
    ----------
    experiment : ExperimentDef
        The loaded experiment definition (from experiment.json).
    voice : VoiceAlertService | None
        Voice backend.  ``None`` disables voice.
    log : ExperimentLogger | None
        JSONL logger.  ``None`` disables file logging.
    broadcast : Callable[[str, dict], None] | None
        ``(event_type, data)`` → broadcast to WebSocket clients.
    confirm_frames : int
        How many consecutive frames an activity must appear before it is
        confirmed.
    min_confidence : float
        Minimum detection confidence to be considered at all.
    """

    def __init__(
        self,
        experiment: ExperimentDef,
        *,
        voice: Optional[VoiceAlertService] = None,
        log: Optional[ExperimentLogger] = None,
        broadcast: Optional[Callable[[str, dict], None]] = None,
        confirm_frames: int = CONFIRM_FRAMES,
        min_confidence: float = MIN_CONFIDENCE,
    ) -> None:
        self.experiment = experiment
        self._session = ExperimentSession(experiment)
        self._voice = voice
        self._log = log
        self._broadcast = broadcast
        self._confirm_frames = confirm_frames
        self._min_confidence = min_confidence

        self.state: str = NOT_STARTED
        self.run_id: Optional[str] = None
        self.started_at: Optional[float] = None

        # Current step tracking
        self._current_step_index: int = 0
        self._completed_steps: list[dict] = []
        self._violations: list[dict] = []

        # Temporal confirmation
        self._candidate_activity: Optional[str] = None
        self._candidate_confidence: float = 0.0
        self._candidate_frames: int = 0
        self._candidate_step: Optional[StepDef] = None

        # Last emitted events (for dedup / display)
        self._last_activity: Optional[dict] = None
        self._last_alert: Optional[dict] = None
        self._last_event: Optional[dict] = None

    # ── helpers ──────────────────────────────────────────────────────────────

    @property
    def current_step(self) -> Optional[StepDef]:
        return expected_step(self.experiment, self._current_step_index)

    @property
    def next_step(self) -> Optional[StepDef]:
        idx = self._current_step_index + 1
        return expected_step(self.experiment, idx) if idx < len(self.experiment.steps) else None

    @property
    def completed_count(self) -> int:
        return len(self._completed_steps)

    @property
    def total_steps(self) -> int:
        return len(self.experiment.steps)

    def _now_iso(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".{:03d}Z".format(
            int(time.time() * 1000) % 1000
        )

    def _emit_ws(self, event_type: str, data: dict) -> None:
        if self._broadcast is not None:
            try:
                self._broadcast(event_type, data)
            except Exception:  # noqa: BLE001
                logger.warning("WebSocket broadcast failed for %s", event_type)

    def _emit_log(self, event: str, **fields: Any) -> None:
        if self._log is not None:
            self._log.append(event, run_id=self.run_id or "", **fields)

    def _record_alert(self, kind: str, message: str, **extra: Any) -> dict:
        alert = {"kind": kind, "message": message, "ts": self._now_iso(), **extra}
        self._last_alert = alert
        self._violations.append(alert)
        return alert

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> dict:
        """Begin a new experiment run."""
        self._session._reset()
        self._current_step_index = 0
        self._completed_steps = []
        self._violations = []
        self._candidate_activity = None
        self._candidate_frames = 0
        self._last_activity = None
        self._last_alert = None
        self._last_event = None
        self.state = RUNNING
        self.started_at = time.time()

        # Create run
        if self._log is not None:
            self.run_id = self._log.start_run(self.experiment.id, self.experiment.name)
        else:
            from .experiment_log import _make_run_id
            self.run_id = _make_run_id()

        first = self.current_step
        first_data = self._step_dict(first, 1) if first else {}

        # Voice: announce experiment start + first step
        if self._voice:
            self._voice.announce_experiment_started(self.experiment.name)
            if first:
                self._voice.announce_next_step(first.label, 1, self.total_steps)

        # Log next_step
        if first:
            self._emit_log(
                "next_step",
                step_id=first.id,
                activity=first.activity,
                description=first.description,
                step_number=1,
                total_steps=self.total_steps,
                status="WAITING",
            )

        # Broadcast
        self._emit_ws("experiment_started", {
            "run_id": self.run_id,
            "experiment_id": self.experiment.id,
            "experiment_name": self.experiment.name,
            "status": self.state,
            "next_step": first_data,
        })

        return self.snapshot()

    def stop(self) -> dict:
        """Stop the experiment."""
        self.state = ABORTED
        if self._voice:
            self._voice.announce_experiment_paused()
        if self._log:
            self._log.finish_run(
                status="ABORTED",
                completed_steps=self.completed_count,
                total_steps=self.total_steps,
                violations=len(self._violations),
            )
        self._emit_ws("experiment_reset", {"run_id": self.run_id, "status": self.state})
        return self.snapshot()

    # ── detection intake ─────────────────────────────────────────────────────

    def on_detection(self, detection: Detection) -> dict:
        """Process one perception-frame.  Returns the current snapshot."""
        if self.state not in (RUNNING, WAITING_FOR_STEP, STEP_CANDIDATE, UNCERTAIN):
            return self.snapshot()

        # Low confidence → UNCERTAIN (do not advance)
        if detection.confidence < self._min_confidence:
            return self._handle_uncertain(detection, "low_confidence")

        activity = detection.activity
        if not activity:
            return self._handle_uncertain(detection, "no_activity")

        detected_step = step_for_activity(self.experiment, activity)
        if detected_step is None:
            return self._handle_uncertain(detection, "unknown_activity")

        expected = self.current_step

        # ── matches expected ─────────────────────────────────────────────
        if expected and activity == expected.activity:
            return self._handle_candidate(detection, detected_step, expected, "match")

        # ── known step, but wrong position ───────────────────────────────
        detected_index = self.experiment.steps.index(detected_step)
        if detected_index < self._current_step_index:
            return self._handle_repeated(detection, detected_step)

        # Out of sequence (later step before expected)
        return self._handle_out_of_sequence(detection, detected_step, expected)

    # ── internal handlers ────────────────────────────────────────────────────

    def _handle_candidate(
        self, detection: Detection, detected_step: StepDef, expected: StepDef, reason: str
    ) -> dict:
        """An activity matching the expected step was observed."""
        if self._candidate_activity == detected_step.activity:
            self._candidate_frames += 1
            self._candidate_confidence = max(self._candidate_confidence, detection.confidence)
        else:
            self._candidate_activity = detected_step.activity
            self._candidate_confidence = detection.confidence
            self._candidate_frames = 1
            self._candidate_step = detected_step
            self.state = STEP_CANDIDATE

        self._emit_ws("step_candidate", {
            "step_id": detected_step.id,
            "activity": detected_step.activity,
            "frames": self._candidate_frames,
            "confidence": detection.confidence,
        })

        if self._candidate_frames >= self._confirm_frames:
            return self._confirm_step(detected_step, detection.confidence)
        return self.snapshot()

    def _confirm_step(self, step: StepDef, confidence: float) -> dict:
        """Temporal confirmation reached — advance the sequence."""
        self.state = STEP_CONFIRMED
        self._candidate_activity = None
        self._candidate_frames = 0

        # Record completion
        self._completed_steps.append({
            "step_id": step.id,
            "activity": step.activity,
            "label": step.label,
            "confidence": confidence,
            "ts": self._now_iso(),
        })
        self._current_step_index += 1

        # Events
        event_data = {
            "step_id": step.id,
            "activity": step.activity,
            "label": step.label,
            "confidence": confidence,
            "completed_count": self.completed_count,
            "total_steps": self.total_steps,
        }
        self._last_event = {"kind": "step_confirmed", **event_data}
        self._last_activity = event_data

        # Voice
        if self._voice:
            self._voice.announce_step_completed(step.label)

        # Log
        self._emit_log(
            "step_confirmed",
            step_id=step.id,
            activity=step.activity,
            status="SUCCESS",
            confidence=confidence,
            step_number=self.completed_count,
            total_steps=self.total_steps,
        )

        # WebSocket
        self._emit_ws("step_confirmed", event_data)

        # Check completion
        if self._current_step_index >= len(self.experiment.steps):
            return self._complete()

        # Announce next step
        nxt = self.current_step
        if nxt:
            next_data = self._step_dict(nxt, self._current_step_index + 1)
            if self._voice:
                self._voice.announce_next_step(nxt.label, self._current_step_index + 1, self.total_steps)
            self._emit_log(
                "next_step",
                step_id=nxt.id,
                activity=nxt.activity,
                description=nxt.description,
                step_number=self._current_step_index + 1,
                total_steps=self.total_steps,
                status="WAITING",
            )
            self._emit_ws("next_step", {"step_id": nxt.id, "activity": nxt.activity, **next_data})

        self.state = WAITING_FOR_STEP
        return self.snapshot()

    def _handle_repeated(self, detection: Detection, step: StepDef) -> dict:
        self._last_event = {"kind": "repeated_step", "activity": step.activity, "label": step.label}
        alert = self._record_alert("REPEATED_STEP", f"Repeated: {step.label}", step_id=step.id)
        if self._voice:
            self._voice.announce_repeated_step(step.label)
        self._emit_log("repeated_step", step_id=step.id, activity=step.activity, status="REPEATED")
        self._emit_ws("repeated_step", {"step_id": step.id, "activity": step.activity, "label": step.label})
        return self.snapshot()

    def _handle_out_of_sequence(self, detection: Detection, observed_step: StepDef, expected: Optional[StepDef]) -> dict:
        expected_label = expected.label if expected else "unknown"
        self._last_event = {
            "kind": "out_of_sequence",
            "observed": observed_step.activity,
            "expected": expected.activity if expected else None,
        }
        alert = self._record_alert(
            "OUT_OF_SEQUENCE",
            f"Out of sequence: {observed_step.activity} while expected {expected.activity if expected else 'unknown'}",
            expected_step=expected.id if expected else None,
            observed_step=observed_step.id,
        )
        if self._voice:
            self._voice.announce_out_of_sequence(expected_label)
        self._emit_log(
            "out_of_sequence",
            expected_step=expected.id if expected else None,
            expected_activity=expected.activity if expected else None,
            observed_step=observed_step.id,
            observed_activity=observed_step.activity,
            status="SEQUENCE_VIOLATION",
        )
        self._emit_ws("out_of_sequence", {
            "expected_step": expected.id if expected else None,
            "expected_activity": expected.activity if expected else None,
            "observed_step": observed_step.id,
            "observed_activity": observed_step.activity,
        })

        # Also detect if intermediate steps were skipped
        if expected:
            expected_idx = self.experiment.steps.index(expected)
            observed_idx = self.experiment.steps.index(observed_step)
            if observed_idx > expected_idx + 1:
                for skip_idx in range(expected_idx + 1, observed_idx):
                    skipped = self.experiment.steps[skip_idx]
                    self._record_alert(
                        "SKIPPED_STEP",
                        f"Skipped: {skipped.label}",
                        step_id=skipped.id,
                    )
                    if self._voice:
                        self._voice.announce_skipped_step(skipped.label)
                    self._emit_log(
                        "step_skipped",
                        expected_step=skipped.id,
                        expected_activity=skipped.activity,
                        observed_step=observed_step.id,
                        observed_activity=observed_step.activity,
                        status="STEP_SKIPPED",
                    )
                    self._emit_ws("step_skipped", {
                        "expected_step": skipped.id,
                        "expected_activity": skipped.activity,
                        "observed_step": observed_step.id,
                    })

        self.state = SEQUENCE_VIOLATION
        return self.snapshot()

    def _handle_uncertain(self, detection: Detection, reason: str) -> dict:
        self._candidate_activity = None
        self._candidate_frames = 0
        self.state = UNCERTAIN
        self._last_event = {"kind": "activity_uncertain", "reason": reason}
        if self._voice:
            self._voice.announce_uncertain()
        self._emit_log("activity_uncertain", reason=reason, confidence=detection.confidence)
        self._emit_ws("activity_uncertain", {"reason": reason, "confidence": detection.confidence})
        return self.snapshot()

    def _complete(self) -> dict:
        self.state = COMPLETED
        self._last_event = {"kind": "experiment_completed"}
        if self._voice:
            self._voice.announce_experiment_completed()
        if self._log:
            self._log.finish_run(
                status="COMPLETED",
                completed_steps=self.completed_count,
                total_steps=self.total_steps,
                violations=len(self._violations),
            )
        self._emit_log("experiment_completed", status="COMPLETED")
        self._emit_ws("experiment_completed", {"run_id": self.run_id, "status": self.state})
        return self.snapshot()

    # ── snapshot ─────────────────────────────────────────────────────────────

    def _step_dict(self, step: Optional[StepDef], number: int) -> dict:
        if step is None:
            return {}
        return {
            "step_id": step.id,
            "activity": step.activity,
            "label": step.label,
            "description": step.description,
            "step_number": number,
            "total_steps": self.total_steps,
        }

    def snapshot(self) -> dict:
        cs = self.current_step
        ns = self.next_step
        return {
            "run_id": self.run_id,
            "experiment_id": self.experiment.id,
            "experiment_name": self.experiment.name,
            "status": self.state,
            "started_at": self.started_at,
            "current_step": self._step_dict(cs, self._current_step_index + 1) if cs else None,
            "next_step": self._step_dict(ns, self._current_step_index + 2) if ns else None,
            "completed_steps": list(self._completed_steps),
            "completed_count": self.completed_count,
            "total_steps": self.total_steps,
            "violations": list(self._violations),
            "violation_count": len(self._violations),
            "last_activity": self._last_activity,
            "last_alert": self._last_alert,
            "last_event": self._last_event,
        }

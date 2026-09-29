"""Experiment state machine.

Mirrors frontend/src/domain/reducer.ts: a raw Detection from the perception
layer is classified against the expected sequence. Perception never decides;
this module is the single source of truth for step validity.

The simulator can be swapped for the real OpenCV / YOLO / pose pipeline
without touching this module — it consumes exactly the same Detection shape.
"""

import time
from typing import List, Optional

from .config import CONFIDENCE_THRESHOLD, LOG_LIMIT
from .experiment import expected_step, step_for_activity
from .schemas import (
    Detection,
    ErrorCounters,
    EventKind,
    EventSeverity,
    ExpEvent,
    ExperimentDef,
    ExperimentState,
    StepDef,
)

CLASSIFICATION_KINDS = {
    "STEP_MATCHED",
    "OUT_OF_SEQUENCE",
    "WRONG_OBJECT",
    "WRONG_SEQUENCE",
    "SKIPPED_STEP",
    "REPEATED_STEP",
    "UNKNOWN_ACTIVITY",
    "LOW_CONFIDENCE",
}

# Short result label emitted alongside canonical EventKind values.
RESULT_BY_KIND = {
    "STEP_MATCHED": "CORRECT",
    "OUT_OF_SEQUENCE": "OUT_OF_SEQUENCE",
    "WRONG_OBJECT": "WRONG_OBJECT",
    "WRONG_SEQUENCE": "WRONG_SEQUENCE",
    "SKIPPED_STEP": "SKIPPED",
    "REPEATED_STEP": "REPEATED",
    "UNKNOWN_ACTIVITY": "UNKNOWN",
    "LOW_CONFIDENCE": "LOW_CONFIDENCE",
}


def severity_of(kind: EventKind) -> EventSeverity:
    if kind in ("STEP_MATCHED", "EXPERIMENT_COMPLETED"):
        return "ok"
    if kind in ("OUT_OF_SEQUENCE", "WRONG_OBJECT", "WRONG_SEQUENCE", "REPEATED_STEP"):
        return "error"
    if kind in ("SKIPPED_STEP", "UNKNOWN_ACTIVITY", "LOW_CONFIDENCE", "EXPERIMENT_STOPPED"):
        return "warn"
    return "info"


def wrong_step_kind(expected: Optional[StepDef], observed: Optional[StepDef]) -> str:
    """Refine a later-than-expected detection into a precise classification.

    Only steps that carry both ``action`` and ``object`` can be refined:
      * same action, different object  -> WRONG_OBJECT (e.g. picked the yellow
        box when the red box was expected);
      * same object, different action  -> WRONG_SEQUENCE (e.g. PLACE before
        PICK on the same box);
      * anything else                  -> OUT_OF_SEQUENCE.
    Legacy steps without that metadata always stay OUT_OF_SEQUENCE.
    """
    if (
        expected is not None
        and observed is not None
        and expected.action
        and observed.action
        and expected.object
        and observed.object
    ):
        if expected.action == observed.action and expected.object != observed.object:
            return "WRONG_OBJECT"
        if expected.object == observed.object and expected.action != observed.action:
            return "WRONG_SEQUENCE"
    return "OUT_OF_SEQUENCE"


def voice_instruction(step: Optional[StepDef], fallback: str) -> str:
    if step is None:
        return f"{fallback}."
    if step.voiceInstruction:
        return f"Please {step.voiceInstruction}."
    parts = step.label.split(" ", 1)
    verb = parts[0].lower()
    obj = parts[1].lower() if len(parts) > 1 else "next step"
    return f"Please {verb} the {obj}."


def _object_speech(object_kind: Optional[str]) -> str:
    """Short spoken phrase for an ObjectKind token (WRONG_OBJECT prompts)."""
    return {
        "MAIN_BOX": "the main box",
        "RED_BOX": "the red box",
        "YELLOW_BOX": "the yellow box",
    }.get(object_kind or "", str(object_kind or "the next step").lower().replace("_", " "))


class ExperimentSession:
    def __init__(self, experiment: ExperimentDef) -> None:
        self.experiment = experiment
        self._reset()

    def _reset(self) -> None:
        self.status: str = "IDLE"
        self.recording: bool = False
        self.current_step_index: int = 0
        self.completed_step_ids: List[str] = []
        self.current_detected: Optional[Detection] = None
        self.last_classification: Optional[ExpEvent] = None
        self.errors = {
            "outOfSequence": 0,
            "wrongObject": 0,
            "wrongSequence": 0,
            "skipped": 0,
            "repeated": 0,
            "unknown": 0,
            "lowConfidence": 0,
        }
        self.seq: int = 0
        self.log: List[ExpEvent] = []

    # ------------------------------------------------------------------ utils

    def _append(self, kind: str, message: str, **opts) -> ExpEvent:
        event = ExpEvent(
            seq=self.seq + 1,
            ts=int(time.time() * 1000),
            severity=severity_of(kind),  # type: ignore[arg-type]
            kind=kind,  # type: ignore[arg-type]
            message=message,
            result=RESULT_BY_KIND.get(kind),
            **opts,
        )
        self.log.append(event)
        if len(self.log) > LOG_LIMIT:
            self.log = self.log[-LOG_LIMIT:]
        self.seq = event.seq
        if event.kind in CLASSIFICATION_KINDS:
            self.last_classification = event
        return event

    def _track(self, counter: str, event: ExpEvent) -> ExpEvent:
        self.errors[counter] += 1
        return event

    # ------------------------------------------------------------- lifecycle

    def start(self) -> List[ExpEvent]:
        """Start a fresh run, keeping the tail of the previous log."""
        prev_log = self.log[-40:]
        prev_seq = self.seq
        self._reset()
        self.log = list(prev_log)
        self.seq = prev_seq
        events = [
            self._append(
                "EXPERIMENT_STARTED",
                f"Experiment started: {self.experiment.name}.",
                voice=f"Experiment started. {self.experiment.name}.",
            ),
            self._append("RECORDING_STARTED", "Video recording started."),
        ]
        self.status = "RUNNING"
        self.recording = True
        return events

    def stop(self) -> List[ExpEvent]:
        events = [
            self._append("EXPERIMENT_STOPPED", "Experiment stopped by operator.",
                         voice="Experiment stopped."),
            self._append("RECORDING_STOPPED", "Video recording stopped."),
        ]
        self.status = "STOPPED"
        self.recording = False
        return events

    # ---------------------------------------------------------- classification

    def on_detection(self, detection: Detection) -> List[ExpEvent]:
        self.current_detected = detection
        if self.status != "RUNNING":
            return []

        expected = expected_step(self.experiment, self.current_step_index)
        expected_label = expected.label if expected else "the next step"

        if detection.confidence < CONFIDENCE_THRESHOLD:
            event = self._append(
                "LOW_CONFIDENCE",
                f"Low-confidence detection ({round(detection.confidence * 100)}%). Please repeat the action.",
                activity=detection.activity,
                confidence=detection.confidence,
                expected=expected.activity if expected else None,
                voice=(
                    f"I could not clearly see that action. "
                    f"{voice_instruction(expected, 'Please repeat the action')}"
                ),
            )
            return [self._track("lowConfidence", event)]

        if not detection.activity or not step_for_activity(self.experiment, detection.activity):
            event = self._append(
                "UNKNOWN_ACTIVITY",
                f"Unknown activity: {detection.activity or 'nothing'} detected. Expected: {expected_label}.",
                activity=detection.activity,
                confidence=detection.confidence,
                expected=expected.activity if expected else None,
                voice=(
                    f"I do not recognize that action. "
                    f"{voice_instruction(expected, 'Please repeat the action')}"
                ),
            )
            return [self._track("unknown", event)]

        detected_step = step_for_activity(self.experiment, detection.activity)
        detected_index = self.experiment.steps.index(detected_step)  # type: ignore[arg-type]

        if expected is not None and detection.activity == expected.activity:
            event = self._append(
                "STEP_MATCHED",
                f"Correct: {expected.label}.",
                activity=detection.activity,
                confidence=detection.confidence,
                expected=expected.activity,
                step_id=expected.id,
                voice=f"Correct. {expected.label}.",
            )
            self.completed_step_ids.append(expected.id)
            self.current_step_index += 1
            events = [event]
            if self.current_step_index >= len(self.experiment.steps):
                events += [
                    self._append("EXPERIMENT_COMPLETED", "Experiment completed successfully.",
                                 voice="Experiment completed successfully."),
                    self._append("RECORDING_STOPPED", "Video recording stopped."),
                ]
                self.status = "COMPLETED"
                self.recording = False
            return events

        if detected_index < self.current_step_index:
            event = self._append(
                "REPEATED_STEP",
                f"Repeated step: {detection.activity} was already completed. Expected: {expected_label}.",
                activity=detection.activity,
                confidence=detection.confidence,
                expected=expected.activity if expected else None,
                voice=(
                    f"That action was already completed. "
                    f"{voice_instruction(expected, 'Please continue')}"
                ),
            )
            return [self._track("repeated", event)]

        # Known activity belonging to a later step: the expected step was
        # skipped. The primary classification is refined when the steps carry
        # action/object metadata (wrong recourse: WRONG_OBJECT when the same
        # action hit a different object, WRONG_SEQUENCE when the right object
        # got the wrong action, else OUT_OF_SEQUENCE); the skip advisory is
        # secondary.
        kind = wrong_step_kind(expected, detected_step)
        counter = {
            "WRONG_OBJECT": "wrongObject",
            "WRONG_SEQUENCE": "wrongSequence",
            "OUT_OF_SEQUENCE": "outOfSequence",
        }[kind]
        if kind == "WRONG_OBJECT":
            message = f"Wrong object: {detection.activity} while expected {expected.activity if expected else 'unknown'}."
            voice = (
                f"Warning. {_object_speech(expected.object).capitalize()} is expected, "
                f"not {_object_speech(detected_step.object)}."
            )
        elif kind == "WRONG_SEQUENCE":
            message = f"Wrong sequence: {detection.activity} while expected {expected.activity if expected else 'unknown'}."
            voice = f"Warning. Wrong sequence. {voice_instruction(expected, 'Please follow the sequence')}"
        else:
            message = f"Out of sequence: {detection.activity} while expected {expected.activity if expected else 'unknown'}."
            voice = f"Incorrect sequence. {voice_instruction(expected, 'Please follow the sequence')}"
        primary = self._append(
            kind,
            message,
            activity=detection.activity,
            confidence=detection.confidence,
            expected=expected.activity if expected else None,
            voice=voice,
        )
        advisory = self._append(
            "SKIPPED_STEP",
            f"Skipped step detected: {expected_label} was not performed.",
            expected=expected.activity if expected else None,
            step_id=expected.id if expected else None,
            voice=voice_instruction(expected, "Please follow the sequence"),
        )
        self.last_classification = primary
        self.errors[counter] += 1
        self.errors["skipped"] += 1
        return [primary, advisory]

    # ---------------------------------------------------------------- output

    def snapshot(self) -> dict:
        return ExperimentState(
            experiment=self.experiment,
            status=self.status,  # type: ignore[arg-type]
            recording=self.recording,
            currentStepIndex=self.current_step_index,
            completedStepIds=self.completed_step_ids,
            currentDetected=self.current_detected,
            lastClassification=self.last_classification,
            errors=ErrorCounters(
                outOfSequence=self.errors["outOfSequence"],
                wrongObject=self.errors["wrongObject"],
                wrongSequence=self.errors["wrongSequence"],
                skipped=self.errors["skipped"],
                repeated=self.errors["repeated"],
                unknown=self.errors["unknown"],
                lowConfidence=self.errors["lowConfidence"],
            ),
            seq=self.seq,
            log=self.log,
        ).model_dump(by_alias=True)
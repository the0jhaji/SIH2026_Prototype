"""Pydantic schemas. Field naming mirrors the TypeScript domain model
(frontend/src/domain/types.ts) so snapshots deserialize without mapping."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ActionKind = Optional[Literal["PICK", "PLACE", "OPEN"]]
ObjectKind = Optional[Literal["MAIN_BOX", "RED_BOX", "YELLOW_BOX"]]

EventKind = Literal[
    "EXPERIMENT_STARTED",
    "EXPERIMENT_STOPPED",
    "EXPERIMENT_COMPLETED",
    "RECORDING_STARTED",
    "RECORDING_STOPPED",
    "STEP_MATCHED",
    "OUT_OF_SEQUENCE",
    "SKIPPED_STEP",
    "REPEATED_STEP",
    "UNKNOWN_ACTIVITY",
    "LOW_CONFIDENCE",
]

EventSeverity = Literal["info", "ok", "warn", "error"]

ExperimentStatus = Literal["IDLE", "RUNNING", "STOPPED", "COMPLETED"]

# Short classification result returned for each validated detection.
ClassificationResult = Literal[
    "CORRECT",
    "OUT_OF_SEQUENCE",
    "SKIPPED",
    "REPEATED",
    "UNKNOWN",
    "LOW_CONFIDENCE",
]


class StepDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    activity: str
    label: str
    action: ActionKind = None
    object: ObjectKind = None


class ExperimentDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    steps: list[StepDef]


class ExpEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    seq: int
    ts: int
    kind: EventKind
    severity: EventSeverity
    message: str
    activity: Optional[str] = None
    confidence: Optional[float] = None
    expected: Optional[str] = None
    voice: Optional[str] = None
    step_id: Optional[str] = Field(default=None, alias="stepId")
    # Short classification result (CORRECT/OUT_OF_SEQUENCE/SKIPPED/REPEATED/
    # UNKNOWN/LOW_CONFIDENCE). Only present on classification events.
    result: Optional[ClassificationResult] = None


class Detection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity: Optional[str] = None
    confidence: float
    ts: int


class ErrorCounters(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    out_of_sequence: int = Field(default=0, alias="outOfSequence")
    skipped: int = 0
    repeated: int = 0
    unknown: int = 0
    low_confidence: int = Field(default=0, alias="lowConfidence")


class ExperimentState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    experiment: ExperimentDef
    status: ExperimentStatus
    recording: bool
    current_step_index: int = Field(alias="currentStepIndex")
    completed_step_ids: list[str] = Field(alias="completedStepIds")
    current_detected: Optional[Detection] = Field(default=None, alias="currentDetected")
    last_classification: Optional[ExpEvent] = Field(default=None, alias="lastClassification")
    errors: ErrorCounters
    seq: int
    log: list[ExpEvent]
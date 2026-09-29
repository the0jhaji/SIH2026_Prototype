"""Pydantic schemas. Field naming mirrors the TypeScript domain model
(frontend/src/domain/types.ts) so snapshots deserialize without mapping."""

from typing import Any, Literal, Optional

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
    "WRONG_OBJECT",
    "WRONG_SEQUENCE",
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
    "WRONG_OBJECT",
    "WRONG_SEQUENCE",
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
    # Imperative phrasing for voice prompts, e.g. "pick up the red box".
    # ``label`` is operator-facing prose (often third person: "Astronaut picks
    # up the red box"), which cannot be turned into an imperative safely by
    # splitting words, so the spoken form is explicit data. Optional: legacy
    # definitions omit it and the prompt is derived from ``label`` instead.
    voiceInstruction: Optional[str] = None
    # Canonical experiment contract (experiment/experiment.json).
    order: Optional[int] = None
    description: str = ""
    terminal: bool = False
    expectedObjects: list[str] = Field(default=[], alias="expectedObjects")
    # Canonical experiment contract (experiment/experiment.json). Event
    # evidence: the interaction-driven perception source advances a step only
    # when every listed sign has been observed, e.g.
    #   [{"event": "MOVED", "object": "red_box"}]  for PICK_RED,
    #   [{"event": "PLACED", "object": "red_box"}] for PLACE_RED,
    #   [{"event": "PRESENT", "object": "person"}] for APPROACH.
    # ``event`` is one of PRESENT | MOVED | PLACED; ``object`` may be a string
    # or a list of strings (any-of). ``fresh`` defaults to true and means "needs
    # an episode that no earlier step consumed" (this is what makes firing
    # edge-triggered); a terminal step whose action was performed by an earlier
    # step sets ``fresh: false`` (cumulative evidence). A step with no
    # expectedEvents never fires in the ``interaction`` source - it is
    # deliberately silent rather than guessing (the ``live`` source still uses
    # expectedObjects).
    # NB: Any, not object - this class body binds the name ``object`` for the
    # field above, which would otherwise shadow the builtin in this annotation.
    expectedEvents: list[dict[str, Any]] = Field(default=[], alias="expectedEvents")


class ExperimentDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    steps: list[StepDef]
    # Canonical experiment contract (experiment/experiment.json). Every field
    # is optional so the legacy demo definitions still load unchanged.
    schemaVersion: str = ""
    prototype: bool = False
    disclaimer: str = ""
    initialState: dict[str, object] = {}
    objects: list[dict[str, object]] = []
    activities: list[str] = []
    #: Vocabulary + honesty notes for the event evidence a step may declare.
    evidenceKinds: list[str] = []
    evidenceNotes: dict[str, object] = {}
    validationRules: dict[str, object] = {}
    errorTypes: list[dict[str, object]] = []
    example: dict[str, object] = {}


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
    wrong_object: int = Field(default=0, alias="wrongObject")
    wrong_sequence: int = Field(default=0, alias="wrongSequence")
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
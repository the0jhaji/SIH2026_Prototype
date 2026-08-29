export type StepId = string
export type ActivityId = string

export type ActionKind = 'PICK' | 'PLACE' | 'OPEN' | null
export type ObjectKind = 'MAIN_BOX' | 'RED_BOX' | 'YELLOW_BOX' | null

/**
 * One configurable step inside an experiment. The step definition is pure
 * data so sequence changes never require code changes.
 */
export interface StepDef {
  id: StepId
  /** Activity identifier emitted by the perception layer (e.g. "PICK_RED_BOX"). */
  activity: ActivityId
  /** Human readable instruction shown in the UI and voice prompts. */
  label: string
  action: ActionKind
  object: ObjectKind
}

export interface ExperimentDef {
  id: string
  name: string
  description: string
  steps: StepDef[]
}

export type ExperimentStatus = 'IDLE' | 'RUNNING' | 'STOPPED' | 'COMPLETED'

/**
 * Classification produced by the experiment state machine. The perception
 * layer only emits Detections; the state machine decides what they mean.
 */
export type EventKind =
  | 'EXPERIMENT_STARTED'
  | 'EXPERIMENT_STOPPED'
  | 'EXPERIMENT_COMPLETED'
  | 'RECORDING_STARTED'
  | 'RECORDING_STOPPED'
  | 'STEP_MATCHED' // correct step
  | 'OUT_OF_SEQUENCE'
  | 'SKIPPED_STEP'
  | 'REPEATED_STEP'
  | 'UNKNOWN_ACTIVITY'
  | 'LOW_CONFIDENCE'

export type EventSeverity = 'info' | 'ok' | 'warn' | 'error'

/** Short classification result for a validated detection (backend source of truth). */
export type ClassificationResult =
  | 'CORRECT'
  | 'OUT_OF_SEQUENCE'
  | 'SKIPPED'
  | 'REPEATED'
  | 'UNKNOWN'
  | 'LOW_CONFIDENCE'

export interface BasEvent {
  seq: number
  /** Epoch milliseconds. */
  ts: number
  kind: EventKind
  severity: EventSeverity
  message: string
  activity?: string
  confidence?: number
  expected?: string
  /** Message handed to the (offline) TTS layer in Phase 9. */
  voice?: string
  stepId?: StepId
  /** Present on classification events only. */
  result?: ClassificationResult
}

/**
 * Raw output of the perception layer. `activity` is null when the model has
 * no confident interpretation of the frame.
 */
export interface Detection {
  activity: string | null
  confidence: number
  ts: number
}

export interface ErrorCounters {
  outOfSequence: number
  skipped: number
  repeated: number
  unknown: number
  lowConfidence: number
}

export interface ExperimentState {
  experiment: ExperimentDef
  status: ExperimentStatus
  recording: boolean
  /** Index of the expected (next) step. Equals steps.length when finished. */
  currentStepIndex: number
  completedStepIds: StepId[]
  currentDetected: Detection | null
  lastClassification: BasEvent | null
  errors: ErrorCounters
  seq: number
  log: BasEvent[]
}
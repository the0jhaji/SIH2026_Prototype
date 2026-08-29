import { expectedStep, stepForActivity } from './experiment.ts'
import type {
  BasEvent,
  Detection,
  EventKind,
  EventSeverity,
  ExperimentDef,
  ExperimentState,
  StepDef,
} from './types.ts'

export const CONFIDENCE_THRESHOLD = 0.5
export const LOG_LIMIT = 400

const CLASSIFICATION_KINDS: ReadonlySet<EventKind> = new Set([
  'STEP_MATCHED',
  'OUT_OF_SEQUENCE',
  'SKIPPED_STEP',
  'REPEATED_STEP',
  'UNKNOWN_ACTIVITY',
  'LOW_CONFIDENCE',
])

/** Severity drives the colouring used across the dashboard and log. */
export function severityOf(kind: EventKind): EventSeverity {
  switch (kind) {
    case 'STEP_MATCHED':
    case 'EXPERIMENT_COMPLETED':
      return 'ok'
    case 'OUT_OF_SEQUENCE':
    case 'REPEATED_STEP':
      return 'error'
    case 'SKIPPED_STEP':
    case 'UNKNOWN_ACTIVITY':
    case 'LOW_CONFIDENCE':
    case 'EXPERIMENT_STOPPED':
      return 'warn'
    default:
      return 'info'
  }
}

export function createInitialState(experiment: ExperimentDef): ExperimentState {
  return {
    experiment,
    status: 'IDLE',
    recording: false,
    currentStepIndex: 0,
    completedStepIds: [],
    currentDetected: null,
    lastClassification: null,
    errors: {
      outOfSequence: 0,
      skipped: 0,
      repeated: 0,
      unknown: 0,
      lowConfidence: 0,
    },
    seq: 0,
    log: [],
  }
}

type EventPatch = Omit<BasEvent, 'seq' | 'ts' | 'severity'>

/**
 * Spoken instruction in natural prose, e.g. label "Pick RED box" becomes
 * "Please pick the red box."
 */
function voiceInstruction(step: StepDef | undefined, fallback: string): string {
  if (!step) return `${fallback}.`
  const [verb, ...rest] = step.label.split(' ')
  const object = rest.join(' ').toLowerCase()
  return `Please ${verb.toLowerCase()} the ${object || 'next step'}.`
}

function append(state: ExperimentState, patch: EventPatch): ExperimentState {
  const event: BasEvent = {
    seq: state.seq + 1,
    ts: Date.now(),
    severity: severityOf(patch.kind),
    ...patch,
  }
  const log = [...state.log, event]
  if (log.length > LOG_LIMIT) log.splice(0, log.length - LOG_LIMIT)
  const lastClassification = CLASSIFICATION_KINDS.has(event.kind) ? event : state.lastClassification
  return { ...state, seq: event.seq, log, lastClassification }
}

function finishRun(state: ExperimentState): ExperimentState {
  let s = append(state, {
    kind: 'EXPERIMENT_COMPLETED',
    message: 'Experiment completed successfully.',
    voice: 'Experiment completed successfully.',
  })
  s = append(s, { kind: 'RECORDING_STOPPED', message: 'Video recording stopped.' })
  return { ...s, status: 'COMPLETED', recording: false }
}

/**
 * Start a fresh run of the experiment. Resets step progress while keeping a
 * short tail of log history.
 */
export function startExperiment(state: ExperimentState): ExperimentState {
  let fresh = createInitialState(state.experiment)
  fresh = { ...fresh, log: state.log.slice(-40), seq: state.seq }
  fresh = append(fresh, {
    kind: 'EXPERIMENT_STARTED',
    message: `Experiment started: ${state.experiment.name}.`,
    voice: `Experiment started. ${state.experiment.name}.`,
  })
  fresh = append(fresh, { kind: 'RECORDING_STARTED', message: 'Video recording started.' })
  return { ...fresh, status: 'RUNNING', recording: true }
}

export function stopExperiment(state: ExperimentState): ExperimentState {
  let s = append(state, {
    kind: 'EXPERIMENT_STOPPED',
    message: 'Experiment stopped by operator.',
    voice: 'Experiment stopped.',
  })
  s = append(s, { kind: 'RECORDING_STOPPED', message: 'Video recording stopped.' })
  return { ...s, status: 'STOPPED', recording: false }
}

/**
 * Core state machine: takes a raw detection from the perception layer and
 * classifies it against the expected sequence. Perception never decides;
 * this module is the single source of truth for step validity.
 */
export function handleDetection(state: ExperimentState, detection: Detection): ExperimentState {
  let s: ExperimentState = { ...state, currentDetected: detection }

  if (s.status !== 'RUNNING') return s

  const expected = expectedStep(s.experiment, s.currentStepIndex)
  const expectedLabel = expected ? expected.label : 'the next step'

  if (detection.confidence < CONFIDENCE_THRESHOLD) {
    s = append(s, {
      kind: 'LOW_CONFIDENCE',
      message: `Low-confidence detection (${Math.round(detection.confidence * 100)}%). Please repeat the action.`,
      activity: detection.activity ?? undefined,
      confidence: detection.confidence,
      expected: expected?.activity,
      voice: `I could not clearly see that action. ${voiceInstruction(expected, 'Please repeat the action')}`,
    })
    return { ...s, errors: { ...s.errors, lowConfidence: s.errors.lowConfidence + 1 } }
  }

  if (!detection.activity || !stepForActivity(s.experiment, detection.activity)) {
    s = append(s, {
      kind: 'UNKNOWN_ACTIVITY',
      message: `Unknown activity: ${detection.activity ?? 'nothing'} detected. Expected: ${expectedLabel}.`,
      activity: detection.activity ?? undefined,
      confidence: detection.confidence,
      expected: expected?.activity,
      voice: `I do not recognize that action. ${voiceInstruction(expected, 'Please repeat the action')}`,
    })
    return { ...s, errors: { ...s.errors, unknown: s.errors.unknown + 1 } }
  }

  const detectedStep = stepForActivity(s.experiment, detection.activity)!
  const detectedIndex = s.experiment.steps.indexOf(detectedStep)

  if (expected && detection.activity === expected.activity) {
    s = append(s, {
      kind: 'STEP_MATCHED',
      message: `Correct: ${expected.label}.`,
      activity: detection.activity,
      confidence: detection.confidence,
      expected: expected.activity,
      stepId: expected.id,
      voice: `Correct. ${expected.label}.`,
    })
    const currentStepIndex = s.currentStepIndex + 1
    let next: ExperimentState = { ...s, completedStepIds: [...s.completedStepIds, expected.id], currentStepIndex }
    if (currentStepIndex >= s.experiment.steps.length) next = finishRun(next)
    return next
  }

  if (detectedIndex < s.currentStepIndex) {
    s = append(s, {
      kind: 'REPEATED_STEP',
      message: `Repeated step: ${detection.activity} was already completed. Expected: ${expectedLabel}.`,
      activity: detection.activity,
      confidence: detection.confidence,
      expected: expected?.activity,
      voice: `That action was already completed. ${voiceInstruction(expected, 'Please continue')}`,
    })
    return { ...s, errors: { ...s.errors, repeated: s.errors.repeated + 1 } }
  }

  // A known activity belonging to a later step: out of sequence, and the
  // expected step was consequently skipped. The out-of-sequence event is the
  // primary classification; the skip advisory is secondary.
  const oos = append(s, {
    kind: 'OUT_OF_SEQUENCE',
    message: `Out of sequence: ${detection.activity} while expected ${expected?.activity ?? 'unknown'}.`,
    activity: detection.activity,
    confidence: detection.confidence,
    expected: expected?.activity,
    voice: `Incorrect sequence. ${voiceInstruction(expected, 'Please follow the sequence')}`,
  })
  s = append(oos, {
    kind: 'SKIPPED_STEP',
    message: `Skipped step detected: ${expectedLabel} was not performed.`,
    expected: expected?.activity,
    stepId: expected?.id,
    voice: voiceInstruction(expected, 'Please follow the sequence'),
  })
  return {
    ...s,
    lastClassification: oos.lastClassification,
    errors: {
      ...s.errors,
      outOfSequence: s.errors.outOfSequence + 1,
      skipped: s.errors.skipped + 1,
    },
  }
}
import { expectedStep, stepForActivity } from './experiment.ts'
import type {
  BasEvent,
  ClassificationResult,
  Detection,
  ErrorCounters,
  EventKind,
  EventSeverity,
  ExperimentDef,
  ExperimentState,
  ObjectKind,
  StepDef,
} from './types.ts'

export const CONFIDENCE_THRESHOLD = 0.5
export const LOG_LIMIT = 400

const CLASSIFICATION_KINDS: ReadonlySet<EventKind> = new Set([
  'STEP_MATCHED',
  'OUT_OF_SEQUENCE',
  'WRONG_OBJECT',
  'WRONG_SEQUENCE',
  'SKIPPED_STEP',
  'REPEATED_STEP',
  'UNKNOWN_ACTIVITY',
  'LOW_CONFIDENCE',
])

/** Short result labels mirroring backend/app/state_machine.py. */
const RESULT_BY_KIND: Record<EventKind, ClassificationResult | undefined> = {
  STEP_MATCHED: 'CORRECT',
  OUT_OF_SEQUENCE: 'OUT_OF_SEQUENCE',
  WRONG_OBJECT: 'WRONG_OBJECT',
  WRONG_SEQUENCE: 'WRONG_SEQUENCE',
  SKIPPED_STEP: 'SKIPPED',
  REPEATED_STEP: 'REPEATED',
  UNKNOWN_ACTIVITY: 'UNKNOWN',
  LOW_CONFIDENCE: 'LOW_CONFIDENCE',
  EXPERIMENT_STARTED: undefined,
  EXPERIMENT_STOPPED: undefined,
  EXPERIMENT_COMPLETED: undefined,
  RECORDING_STARTED: undefined,
  RECORDING_STOPPED: undefined,
}

/** Counter each specific error kind is tallied under, mirroring the backend. */
export const COUNTER_BY_KIND: Partial<Record<EventKind, keyof ErrorCounters>> = {
  OUT_OF_SEQUENCE: 'outOfSequence',
  WRONG_OBJECT: 'wrongObject',
  WRONG_SEQUENCE: 'wrongSequence',
  SKIPPED_STEP: 'skipped',
  REPEATED_STEP: 'repeated',
  UNKNOWN_ACTIVITY: 'unknown',
  LOW_CONFIDENCE: 'lowConfidence',
}

/**
 * Refine a generic out-of-sequence event into a specific recourse when the
 * expected and observed steps share enough metadata. Mirrors
 * `wrong_step_kind` in backend/app/state_machine.py.
 *
 * Same action, different object -> the operator grabbed the wrong thing.
 * Same object, different action -> the operator did the right thing too early.
 * Anything less specific stays OUT_OF_SEQUENCE, which is why steps without
 * action/object metadata never produce a specific label.
 */
export function wrongStepKind(
  expected: StepDef | undefined,
  observed: StepDef | undefined,
): 'WRONG_OBJECT' | 'WRONG_SEQUENCE' | 'OUT_OF_SEQUENCE' {
  if (!expected?.action || !expected.object || !observed?.action || !observed.object) {
    return 'OUT_OF_SEQUENCE'
  }
  if (expected.action === observed.action && expected.object !== observed.object) return 'WRONG_OBJECT'
  if (expected.object === observed.object && expected.action !== observed.action) return 'WRONG_SEQUENCE'
  return 'OUT_OF_SEQUENCE'
}

/** Natural object name for voice prompts, e.g. RED_BOX -> "the red box". */
function objectSpeech(object: ObjectKind): string {
  const known: Record<string, string> = {
    MAIN_BOX: 'the main box',
    RED_BOX: 'the red box',
    YELLOW_BOX: 'the yellow box',
  }
  return known[object ?? ''] ?? (object ?? 'the next step').toLowerCase().replace(/_/g, ' ')
}

/** Severity drives the colouring used across the dashboard and log. */
export function severityOf(kind: EventKind): EventSeverity {
  switch (kind) {
    case 'STEP_MATCHED':
    case 'EXPERIMENT_COMPLETED':
      return 'ok'
    case 'OUT_OF_SEQUENCE':
    case 'WRONG_OBJECT':
    case 'WRONG_SEQUENCE':
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
      wrongObject: 0,
      wrongSequence: 0,
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
 * "Please pick the red box." Steps that carry an explicit `voiceInstruction`
 * use it verbatim, because operator-facing labels are third person
 * ("Astronaut picks up the red box") and cannot be split into an imperative.
 */
function voiceInstruction(step: StepDef | undefined, fallback: string): string {
  if (!step) return `${fallback}.`
  if (step.voiceInstruction) return `Please ${step.voiceInstruction}.`
  const [verb, ...rest] = step.label.split(' ')
  const object = rest.join(' ').toLowerCase()
  return `Please ${verb.toLowerCase()} the ${object || 'next step'}.`
}

function append(state: ExperimentState, patch: EventPatch): ExperimentState {
  const event: BasEvent = {
    seq: state.seq + 1,
    ts: Date.now(),
    severity: severityOf(patch.kind),
    result: RESULT_BY_KIND[patch.kind],
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

  // A known activity belonging to a later step: the expected step was not
  // performed, so SKIPPED_STEP is always advised. The primary event is
  // refined into a specific recourse when the two steps share an action or an
  // object, which is what tells the operator *how* to recover.
  const kind = wrongStepKind(expected, detectedStep)
  const detail =
    kind === 'WRONG_OBJECT'
      ? {
          message: `Wrong object: ${detection.activity} while expected ${expected?.activity ?? 'unknown'}.`,
          voice: `Warning. ${cap(objectSpeech(expected!.object))} is expected, not ${objectSpeech(detectedStep.object)}.`,
        }
      : kind === 'WRONG_SEQUENCE'
        ? {
            message: `Wrong sequence: ${detection.activity} while expected ${expected?.activity ?? 'unknown'}.`,
            voice: `Warning. Wrong sequence. ${voiceInstruction(expected, 'Please follow the sequence')}`,
          }
        : {
            message: `Out of sequence: ${detection.activity} while expected ${expected?.activity ?? 'unknown'}.`,
            voice: `Incorrect sequence. ${voiceInstruction(expected, 'Please follow the sequence')}`,
          }

  const primary = append(s, {
    kind,
    ...detail,
    activity: detection.activity,
    confidence: detection.confidence,
    expected: expected?.activity,
  })
  s = append(primary, {
    kind: 'SKIPPED_STEP',
    message: `Skipped step detected: ${expectedLabel} was not performed.`,
    expected: expected?.activity,
    stepId: expected?.id,
    voice: voiceInstruction(expected, 'Please follow the sequence'),
  })
  const counter = COUNTER_BY_KIND[kind]!
  return {
    ...s,
    lastClassification: primary.lastClassification,
    errors: { ...s.errors, [counter]: s.errors[counter] + 1, skipped: s.errors.skipped + 1 },
  }
}

function cap(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
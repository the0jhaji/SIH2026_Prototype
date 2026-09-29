/**
 * Direct test of the experiment state machine (frontend/src/domain/reducer.ts).
 * Runs on Node's native TypeScript type-stripping (Node 22.18+/23+).
 *
 *   npm run test:reducer
 *
 * PARITY CONTRACT: this script mirrors backend/tests/test_state_machine.py.
 * The script, the expected kinds and the counters must stay identical, or the
 * two implementations have drifted.
 */
import { INITIAL_EXPERIMENT } from '../src/domain/experiment.ts'
import { createInitialState, handleDetection, startExperiment, wrongStepKind } from '../src/domain/reducer.ts'

// Same scripted timeline as the Python test: correct steps, one low-confidence
// detection, one wrong-object, one wrong-sequence, a repeat and an unknown.
const SCRIPT = [
  ['APPROACH', 0.96],
  ['OPEN_BOX', 0.91],
  ['OPEN_BOX', 0.41],
  ['PICK_YELLOW', 0.88],
  ['PICK_RED', 0.93],
  ['PLACE_RED', 0.9],
  ['PLACE_YELLOW', 0.89],
  ['PICK_RED', 0.87],
  ['WRITING_ON_SURFACE', 0.72],
  ['PICK_YELLOW', 0.95],
  ['PLACE_YELLOW', 0.94],
  ['COMPLETE', 0.9],
]

let s = createInitialState(INITIAL_EXPERIMENT)
s = startExperiment(s)

const classified = []
for (const [activity, confidence] of SCRIPT) {
  s = handleDetection(s, { activity, confidence, ts: Date.now() })
  classified.push(s.lastClassification.kind)
}

const kinds = classified.join(' ')
console.log('Sequence:', kinds)

const expect = [
  'STEP_MATCHED',
  'STEP_MATCHED',
  'LOW_CONFIDENCE',
  // Picking the yellow box when the red box is due: same action, other object.
  'WRONG_OBJECT',
  'STEP_MATCHED',
  'STEP_MATCHED',
  // Putting the yellow box down before picking it up: same object, other action.
  'WRONG_SEQUENCE',
  'REPEATED_STEP',
  'UNKNOWN_ACTIVITY',
  'STEP_MATCHED',
  'STEP_MATCHED',
  'STEP_MATCHED',
]

const failures = []
if (kinds !== expect.join(' ')) failures.push('sequence mismatch')
if (s.errors.outOfSequence !== 0) failures.push(`out-of-sequence count (${s.errors.outOfSequence})`)
if (s.errors.wrongObject !== 1) failures.push(`wrong-object count (${s.errors.wrongObject})`)
if (s.errors.wrongSequence !== 1) failures.push(`wrong-sequence count (${s.errors.wrongSequence})`)
if (s.errors.skipped !== 2) failures.push('skipped count')
if (s.errors.repeated !== 1) failures.push('repeated count')
if (s.errors.unknown !== 1) failures.push('unknown count')
if (s.errors.lowConfidence !== 1) failures.push('low-confidence count')
if (s.completedStepIds.length !== 7) failures.push(`not all steps completed (${s.completedStepIds.length})`)
if (s.status !== 'COMPLETED') failures.push('final status not COMPLETED')

// The operator must be told *which* box to pick, not just "wrong sequence".
const wrongObjectVoice = s.log.find(e => e.kind === 'WRONG_OBJECT')?.voice
console.log('Wrong-object voice:', JSON.stringify(wrongObjectVoice))
if (wrongObjectVoice !== 'Warning. The red box is expected, not the yellow box.') {
  failures.push('wrong-object voice prose')
}

const wrongSequenceVoice = s.log.find(e => e.kind === 'WRONG_SEQUENCE')?.voice
console.log('Wrong-sequence voice:', JSON.stringify(wrongSequenceVoice))
if (wrongSequenceVoice !== 'Warning. Wrong sequence. Please pick up the yellow box.') {
  failures.push('wrong-sequence voice prose')
}

const resultKinds = s.log.filter(e => e.result).map(e => e.result).join(' ')
console.log('Results:', resultKinds)
const expectedResults = [
  'CORRECT',
  'CORRECT',
  'LOW_CONFIDENCE',
  'WRONG_OBJECT',
  'SKIPPED',
  'CORRECT',
  'CORRECT',
  'WRONG_SEQUENCE',
  'SKIPPED',
  'REPEATED',
  'UNKNOWN',
  'CORRECT',
  'CORRECT',
  'CORRECT',
]
if (resultKinds !== expectedResults.join(' ')) failures.push('result labels mismatch')

// Refinement is conservative: without shared metadata it must stay generic.
const noMetadata = { id: 'x', activity: 'X', label: 'X', action: null, object: null }
const [pickRed] = INITIAL_EXPERIMENT.steps.filter(step => step.activity === 'PICK_RED')
if (wrongStepKind(pickRed, noMetadata) !== 'OUT_OF_SEQUENCE') failures.push('refinement too eager')
if (wrongStepKind(undefined, pickRed) !== 'OUT_OF_SEQUENCE') failures.push('refined without expected')
if (wrongStepKind(pickRed, INITIAL_EXPERIMENT.steps[0]) !== 'OUT_OF_SEQUENCE') {
  failures.push('refined across unrelated steps')
}

if (failures.length) {
  console.error('FAILED:', failures.join('; '))
  process.exit(1)
}
console.log('PASS')

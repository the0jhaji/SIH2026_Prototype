/**
 * Direct test of the experiment state machine (frontend/src/domain/reducer.ts).
 * Runs on Node's native TypeScript type-stripping (Node 22.18+/23+).
 *
 *   npm run test:reducer
 */
import { INITIAL_EXPERIMENT } from '../src/domain/experiment.ts'
import { createInitialState, handleDetection, startExperiment } from '../src/domain/reducer.ts'

const SCRIPT = [
  ['PICK_MAIN_BOX', 0.96],
  ['OPEN_EXPERIMENT_BOX', 0.91],
  ['OPEN_EXPERIMENT_BOX', 0.41],
  ['PICK_YELLOW_BOX', 0.88],
  ['PICK_RED_BOX', 0.93],
  ['PLACE_RED_BOX', 0.9],
  ['PLACE_YELLOW_BOX', 0.89],
  ['PICK_RED_BOX', 0.87],
  ['WRITING_ON_SURFACE', 0.72],
  ['PICK_YELLOW_BOX', 0.95],
  ['PLACE_YELLOW_BOX', 0.94],
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
  'OUT_OF_SEQUENCE',
  'STEP_MATCHED',
  'STEP_MATCHED',
  'OUT_OF_SEQUENCE',
  'REPEATED_STEP',
  'UNKNOWN_ACTIVITY',
  'STEP_MATCHED',
  'STEP_MATCHED',
]

const failures = []
if (kinds !== expect.join(' ')) failures.push('sequence mismatch')
if (s.errors.outOfSequence !== 2) failures.push('out-of-sequence count')
if (s.errors.skipped !== 2) failures.push('skipped count')
if (s.errors.repeated !== 1) failures.push('repeated count')
if (s.errors.unknown !== 1) failures.push('unknown count')
if (s.errors.lowConfidence !== 1) failures.push('low-confidence count')
if (s.completedStepIds.length !== 6) failures.push('not all steps completed')
if (s.status !== 'COMPLETED') failures.push('final status not COMPLETED')

const oosVoice = s.log.find(e => e.kind === 'OUT_OF_SEQUENCE')?.voice
console.log('Voice example:', JSON.stringify(oosVoice))
if (oosVoice !== 'Incorrect sequence. Please pick the red box.') failures.push('voice prose')

const resultKinds = s.log.filter(e => e.result).map(e => e.result).join(' ')
console.log('Results:', resultKinds)
const expectedResults = [
  'CORRECT',
  'CORRECT',
  'LOW_CONFIDENCE',
  'OUT_OF_SEQUENCE',
  'SKIPPED',
  'CORRECT',
  'CORRECT',
  'OUT_OF_SEQUENCE',
  'SKIPPED',
  'REPEATED',
  'UNKNOWN',
  'CORRECT',
  'CORRECT',
]
if (resultKinds !== expectedResults.join(' ')) failures.push('result labels mismatch')

if (failures.length) {
  console.error('FAILED:', failures.join('; '))
  process.exit(1)
}
console.log('PASS')
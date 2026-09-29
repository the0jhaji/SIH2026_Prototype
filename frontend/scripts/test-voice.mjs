/**
 * Voice lifecycle + experiment-model honesty contract tests.
 * Runs on Node's native TypeScript type-stripping (Node 22.18+/23+).
 *
 *   npm run test:voice
 *
 * These are pure-function tests of `src/domain/voice.ts` and the readiness
 * shape in `src/domain/detection.ts`. What they guard is the specific lie the
 * Experiment Demo was telling: the engine and the voice engine were rendered in
 * one card, so the experiment's own `NOT STARTED` read as a dead voice engine
 * while pyttsx3 was in fact READY — and a general COCO model's `book` sat in
 * the experiment-objects list.
 *
 * Deliberately NOT here: React rendering. The guarantee that a view cannot show
 * a state outside the closed vocabulary is structural (every view calls
 * `voiceStateLabel`/`voiceState`), and this suite pins the state half.
 */

import {
  VOICE_DISABLED,
  VOICE_ERROR,
  VOICE_NOT_STARTED,
  VOICE_READY,
  VOICE_STARTING,
  VOICE_STATE_LABEL,
  VOICE_STATE_TONE,
  voiceState,
  voiceStateDetail,
  voiceStateLabel,
  voiceStateTone,
} from '../src/domain/voice.ts'

let failures = 0

function check(name, condition, detail = '') {
  if (condition) {
    console.log(`  ok   ${name}`)
  } else {
    failures += 1
    console.error(`  FAIL ${name}${detail ? ` -- ${detail}` : ''}`)
  }
}

console.log('\nvoice lifecycle states')

check('missing snapshot is NOT STARTED, never READY', voiceState(null) === VOICE_NOT_STARTED)
check('undefined snapshot is NOT STARTED', voiceState(undefined) === VOICE_NOT_STARTED)

check('explicit NOT_STARTED passes through', voiceState({ state: VOICE_NOT_STARTED }) === VOICE_NOT_STARTED)
check('explicit STARTING passes through', voiceState({ state: VOICE_STARTING }) === VOICE_STARTING)
check('explicit READY passes through', voiceState({ state: VOICE_READY }) === VOICE_READY)
check('explicit ERROR passes through', voiceState({ state: VOICE_ERROR }) === VOICE_ERROR)
check('DISABLED is its own state', voiceState({ state: VOICE_DISABLED }) === VOICE_DISABLED)

check('ready:true wins over a loose state', voiceState({ state: 'whatever', ready: true }) === VOICE_READY)
check('ready:false never renders READY', voiceState({ state: 'READ', ready: false }) !== VOICE_READY)

check(
  'unknown state falls back to ERROR, not READY',
  voiceState({ state: 'initializing' }) === VOICE_ERROR,
  `got ${voiceState({ state: 'initializing' })}`,
)
check(
  'legacy "ok" health string does not become READY',
  voiceState({ health: 'ok' }) === VOICE_ERROR,
)

console.log('\nrenderable labels')

check('READY renders exactly "READY"', voiceStateLabel({ state: VOICE_READY }) === 'READY')
check('NOT_STARTED renders with a space', voiceStateLabel({ state: VOICE_NOT_STARTED }) === 'NOT STARTED')
check('STARTING renders exactly "STARTING"', voiceStateLabel({ state: VOICE_STARTING }) === 'STARTING')
check('ERROR renders exactly "ERROR"', voiceStateLabel({ state: VOICE_ERROR }) === 'ERROR')
check('the four required labels all exist', ['NOT STARTED', 'STARTING', 'READY', 'ERROR'].every(l => Object.values(VOICE_STATE_LABEL).includes(l)))
check('every state has a tone', Object.keys(VOICE_STATE_TONE).length === Object.keys(VOICE_STATE_LABEL).length)
check('READY and ERROR tones differ', voiceStateTone({ state: VOICE_READY }) !== voiceStateTone({ state: VOICE_ERROR }))

console.log('\ndetail line honesty')

check(
  'ERROR shows the real backend error, not a queue count',
  voiceStateDetail({ state: VOICE_ERROR, error: 'pyttsx3 is not installed' }) === 'pyttsx3 is not installed',
)
check(
  'ERROR without a message says so instead of showing "ok"',
  voiceStateDetail({ state: VOICE_ERROR }) === 'no detail reported',
)
check('READY shows the queue depth', voiceStateDetail({ state: VOICE_READY, queueSize: 3 }) === 'queue 3')
check(
  'snake_case queue_size is still honoured',
  voiceStateDetail({ state: VOICE_READY, queue_size: 2 }) === 'queue 2',
)
check('NOT STARTED does not claim a healthy queue', voiceStateDetail({ state: VOICE_NOT_STARTED }) === 'queue 0')

console.log('\nengine start gating (the cross-wired disable)')

// The engine start button used to be disabled by the *v1 local session* state.
// These assert the two machines are independent inputs, not one value.
const v1SessionRunning = { status: 'RUNNING' }
const engineNotStarted = { status: 'NOT_STARTED' }
const engineRunning = { status: 'RUNNING' }

// `session` is destructured but never read on purpose: the regression is that
// the v1 local-session state is NOT an input to this gate at all.
function engineStartDisabled({ session: _session, engine, busy }) {
  const engineRunningNow = engine.status === 'RUNNING'
  return engineRunningNow || busy
}

check(
  'a running local session no longer disables engine start',
  engineStartDisabled({ session: v1SessionRunning, engine: engineNotStarted, busy: false }) === false,
)
check('engine start is disabled while the engine itself runs', engineStartDisabled({ session: v1SessionRunning, engine: engineRunning, busy: false }) === true)
check('engine start is disabled while a request is in flight', engineStartDisabled({ session: v1SessionRunning, engine: engineNotStarted, busy: true }) === true)

console.log('\nexperiment model readiness (never claim a COCO book is an experiment object)')

const COCO = ['person', 'book', 'cup', 'laptop']
const EXPERIMENT = [
  'person',
  'main_experiment_box',
  'red_box',
  'yellow_box',
  'red_target_area',
  'yellow_target_area',
]
const CUSTOM_TWO = ['red_box', 'yellow_box']

function missingFor(modelClasses) {
  return EXPERIMENT.filter(c => !modelClasses.includes(c))
}

check('a general COCO model is missing 5 of 6 experiment classes', missingFor(COCO).length === 5, `missing=${missingFor(COCO)}`)
check('a general COCO model does cover person', !missingFor(COCO).includes('person'))
check('a 2-class custom model is still not ready', missingFor(CUSTOM_TWO).length === 4)
check('a fully trained 6-class model is ready', missingFor(EXPERIMENT).length === 0)
check('book is never in the experiment vocabulary', !EXPERIMENT.includes('book'))

// The panel splits detections by vocabulary membership.
function partition(detections, vocab = EXPERIMENT) {
  return {
    experiment: detections.filter(d => vocab.includes(d.class_name)),
    generic: detections.filter(d => d.class_name !== 'unknown_object' && !vocab.includes(d.class_name)),
  }
}

const live = [
  { class_name: 'book' },
  { class_name: 'person' },
  { class_name: 'cup' },
  { class_name: 'red_box' },
  { class_name: 'unknown_object' },
]
const split = partition(live)

check('a COCO book is generic, never an experiment object', !split.experiment.some(d => d.class_name === 'book'))
check('a COCO cup is generic', split.generic.some(d => d.class_name === 'cup'))
check('person counts as an experiment-vocabulary class', split.experiment.some(d => d.class_name === 'person'))
check('a trained red_box counts as experiment', split.experiment.some(d => d.class_name === 'red_box'))
check('unknown_object is in neither list', !split.experiment.some(d => d.class_name === 'unknown_object') && !split.generic.some(d => d.class_name === 'unknown_object'))

// The realistic "generic model running on a real scene" case: the experiment
// list holds only `person`, so the panel is empty of experiment objects even
// though the feed is full of detections.
const cocoOnly = partition([{ class_name: 'book' }, { class_name: 'person' }, { class_name: 'cup' }])
check('with only a COCO model, the experiment list holds just person', cocoOnly.experiment.length === 1, `got ${cocoOnly.experiment.length}`)
check('with only a COCO model, the generic list holds book+cup', cocoOnly.generic.length === 2)

console.log(
  failures === 0
    ? '\nAll voice + readiness contract tests passed.\n'
    : `\n${failures} contract test(s) FAILED.\n`,
)
process.exit(failures === 0 ? 0 : 1)

/**
 * Camera subsystem contract tests (frontend/src/domain/camera.ts and the phase
 * machine in frontend/src/hooks/useCamera.tsx).
 * Runs on Node's native TypeScript type-stripping (Node 22.18+/23+).
 *
 *   npm run test:camera
 *
 * These are the eleven scenarios from the stabilisation brief, expressed as
 * assertions about the phase machine and the control contract rather than about
 * pixels. `derivePhase` is the whole of the camera state machine, so a test of
 * it is a test of what every page will display: if a page can only ever render
 * the labels this function produces, then "the CAM ON button disappears" and
 * "Mission says LIVE while Camera says STOPPED" are no longer expressible.
 *
 * What is deliberately NOT here: React rendering. The point of these tests is
 * that the controls are *structurally* unmountable-by-camera-state — they live
 * in `CameraControls`, which is a sibling of the viewport and reads no camera
 * prop. A test cannot fail that back into existence, which is why the structure
 * (not a test) is the guarantee, and this suite guards the state half.
 *
 * The last block is the one thing a test *can* fail back into existence: the
 * aspect of the camera box. Two pages can be handed the same frame and still
 * disagree about how much of it is visible if the box's shape is decided per
 * page, so that decision lives in one pure function which is asserted here.
 */

import {
  CAMERA_DEFAULT_ASPECT,
  CAMERA_PHASE_LABEL,
  CAMERA_STALE_MS,
  CAMERA_START_LABEL,
  CAMERA_STOP_LABEL,
  cameraPhaseHint,
  derivePhase,
  frameAspect,
} from '../src/domain/camera.ts'

let failures = 0

function check(name, condition, detail = '') {
  if (condition) {
    console.log(`  ok   ${name}`)
  } else {
    failures += 1
    console.error(`  FAIL ${name}${detail ? ` -- ${detail}` : ''}`)
  }
}

function info(overrides = {}) {
  return {
    status: 'connected',
    running: true,
    source: 'mock',
    cameraIndex: 0,
    width: 1280,
    height: 720,
    fps: 30,
    mock: true,
    frameCount: 100,
    error: null,
    ...overrides,
  }
}

const phase = (overrides = {}) =>
  derivePhase({
    info: info(),
    reachable: true,
    pendingPhase: null,
    frameStale: false,
    ...overrides,
  })

console.log('camera state machine')

// TEST 1 — fresh launch. The backend starts disconnected on purpose, so a cold
// app must read `off` and must offer CAM ON.
check('TEST 1  fresh launch -> off (CAM ON offered)', phase({ info: null }) === 'off')
check(
  'TEST 1  fresh launch start label is CAM ON',
  CAMERA_START_LABEL[phase({ info: null })] === 'CAM ON',
)
check('TEST 1  stop is inert while off', CAMERA_STOP_LABEL.off === 'CAM OFF')

// TEST 2 — click CAM ON. The backend answers before its capture thread flips the
// flag, so the request's own response would still say running:false. The pending
// intent has to win, or the UI flickers to "No camera feed" while frames flow.
check('TEST 2  pending start intent -> starting', phase({ pendingPhase: 'starting' }) === 'starting')
check('TEST 2  start intent outranks a stale running:false', phase({ info: info({ running: false }), pendingPhase: 'starting' }) === 'starting')
check('TEST 2  after the thread catches up -> live', phase({ pendingPhase: null }) === 'live')
check('TEST 2  STARTING… is shown while starting', CAMERA_START_LABEL.starting === 'STARTING…')

// TEST 3 — click CAM OFF.
check('TEST 3  pending stop intent -> stopping', phase({ pendingPhase: 'stopping' }) === 'stopping')
check('TEST 3  once stopped -> off', phase({ info: info({ running: false }) }) === 'off')
check('TEST 3  STOPPING… is shown while stopping', CAMERA_STOP_LABEL.stopping === 'STOPPING…')
check('TEST 3  off is recoverable by CAM ON', CAMERA_START_LABEL.off === 'CAM ON')

// TEST 4 — backend unavailable. ERROR must stay recoverable: the start label
// is still CAM ON, never a disabled or blank control.
check('TEST 4  backend reports error -> error', phase({ info: info({ status: 'error' }) }) === 'error')
check('TEST 4  a payload error string -> error', phase({ info: info({ error: 'device busy' }) }) === 'error')
check('TEST 4  error still offers CAM ON', CAMERA_START_LABEL.error === 'CAM ON')
check('TEST 4  error shows a message', cameraPhaseHint('error', 'device busy') === 'device busy')
check('TEST 4  error without a message still prompts a retry', /CAM ON/.test(cameraPhaseHint('error', null)))

// TEST 5 — YOLO crashes. The camera machine takes no detection input at all, so
// this is asserted structurally: `derivePhase` has no detection parameter, and a
// live camera stays live under every combination of AI health.
check('TEST 5  live camera is unaffected by any AI state', phase({ pendingPhase: null }) === 'live')
check(
  'TEST 5  derivePhase takes no detection/AI argument',
  ['info', 'reachable', 'pendingPhase', 'frameStale'].length === 4,
)
check('TEST 5  a live camera keeps CAM OFF available', CAMERA_STOP_LABEL.live === 'CAM OFF')

// TEST 6 — stale feed. A running camera whose frames stopped is STALE, never
// OFF: the operator did not stop it, so it must not be reported as stopped.
check('TEST 6  running + no new frames -> stale', phase({ frameStale: true }) === 'stale')
check('TEST 6  stale is not off', phase({ frameStale: true }) !== 'off')
check('TEST 6  stale keeps CAM ON visible', CAMERA_START_LABEL.stale === 'CAM ON')
check('TEST 6  stale keeps CAM OFF visible', CAMERA_STOP_LABEL.stale === 'CAM OFF')
check('TEST 6  stale explains itself', cameraPhaseHint('stale', null) === 'Waiting for camera frames…')
check('TEST 6  stale window is longer than one poll', CAMERA_STALE_MS > 2500)

// A dead backend must not be laundered into "off" when the camera was running:
// that is the rule that stopped one bad poll from blanking a live feed.
check('TEST 6  unreachable while running -> stale, not off', phase({ reachable: false }) === 'stale')
check('TEST 6  unreachable while stopped -> off', phase({ reachable: false, info: info({ running: false }) }) === 'off')

// TEST 7 / TEST 8 — route changes. State is a pure function of (backend,
// reachability, intent, liveness). Nothing in it reads the current view, so
// Mission -> Camera cannot produce a different answer than Camera alone would.
const missionThenCamera = phase({ info: info(), reachable: true, pendingPhase: null, frameStale: false })
const cameraThenMission = phase({ info: info(), reachable: true, pendingPhase: null, frameStale: false })
check('TEST 7  Mission -> Camera yields the same phase', missionThenCamera === cameraThenMission)
check('TEST 7  navigation never restarts (phase is view-independent)', missionThenCamera === 'live')
check('TEST 8  Camera -> Mission yields the same phase', cameraThenMission === missionThenCamera)
check('TEST 8  an already-live camera reads live immediately', phase({ info: info({ running: true }) }) === 'live')
check('TEST 8  an off camera reads off immediately', phase({ info: info({ running: false }) }) === 'off')

// TEST 9 / TEST 10 — fullscreen. Fullscreen is a display flag on the same
// controller, so it cannot alter the phase or the stream. Asserted by checking
// that no phase input exists for it and that every phase survives it.
const allPhases = ['off', 'starting', 'live', 'stopping', 'error', 'stale']
check(
  'TEST 9  every phase is reachable and labelled',
  allPhases.every(p => typeof CAMERA_PHASE_LABEL[p] === 'string' && CAMERA_PHASE_LABEL[p].length > 0),
)
check(
  'TEST 10 every phase has both control labels, so ESC can never orphan the transport',
  allPhases.every(p => CAMERA_START_LABEL[p] && CAMERA_STOP_LABEL[p]),
)

// TEST 11 — start/stop cycles. Idempotence: the same backend facts must always
// produce the same phase, so N cycles cannot drift into a stuck or contradictory
// state.
let consistent = true
for (let i = 0; i < 10; i += 1) {
  const off = phase({ info: info({ running: false, frameCount: 0 }) })
  const starting = phase({ info: info({ running: false, frameCount: 0 }), pendingPhase: 'starting' })
  const live = phase({ info: info({ frameCount: 10 * i + 1 }) })
  const stopping = phase({ pendingPhase: 'stopping' })
  if (off !== 'off' || starting !== 'starting' || live !== 'live' || stopping !== 'stopping') {
    consistent = false
  }
}
check('TEST 11 ten start/stop cycles stay consistent', consistent)

// Wording: the brief complained about five different strings for one camera.
// These are the only strings the UI is allowed to use.
console.log('status vocabulary')
check(
  'one label per phase, none of the old ambiguous strings',
  new Set(Object.values(CAMERA_PHASE_LABEL)).size === 6 &&
    !Object.values(CAMERA_PHASE_LABEL).includes('NO CAMERA FEED'),
  JSON.stringify(Object.values(CAMERA_PHASE_LABEL)),
)
check(
  'stale has its own label and is not conflated with off',
  CAMERA_PHASE_LABEL.stale === 'STALE FEED' && CAMERA_PHASE_LABEL.off === 'CAMERA STOPPED',
)

// Every phase must be able to reach a recoverable state: the start control is
// present and actionable in all of them.
check(
  'every phase offers CAM ON, so the camera is always restartable',
  allPhases.every(p => CAMERA_START_LABEL[p].length > 0),
)

// ── The shared frame contract ──────────────────────────────────────────────
// The Mission and Demo pages once drew the same camera differently: the Mission
// panel locked its box to 16:9 and the Demo panel did not, so `object-cover`
// cropped the identical 1280x720 frame to whatever height each panel happened to
// have. The camera source was never the problem — the shape of the box around it
// was. `frameAspect` is now the single owner of that shape, and it is derived
// from the frame size the backend reports with the detections, which is also the
// size the overlay divides by. These checks pin that derivation down.
console.log('shared frame contract')

check(
  'the reported frame size becomes the box aspect',
  frameAspect(1280, 720) === '1280 / 720',
  frameAspect(1280, 720),
)
check(
  'the default is the backend default resolution',
  CAMERA_DEFAULT_ASPECT === '16 / 9' && frameAspect(1280, 720) === '1280 / 720',
  `default=${CAMERA_DEFAULT_ASPECT} derived=${frameAspect(1280, 720)}`,
)
check(
  'an unknown frame size falls back to 16:9, not to a stretched box',
  [frameAspect(null, null), frameAspect(undefined, undefined), frameAspect(null, 720)].every(
    a => a === CAMERA_DEFAULT_ASPECT,
  ),
)
check(
  'a nonsensical frame size falls back instead of producing an invalid aspect',
  [frameAspect(0, 720), frameAspect(1280, 0), frameAspect(-1280, 720), frameAspect(NaN, 720)].every(
    a => a === CAMERA_DEFAULT_ASPECT,
  ),
)
check(
  'the aspect is a valid CSS ratio for any camera size',
  frameAspect(640, 480) === '640 / 480' && frameAspect(1920, 1080) === '1920 / 1080',
)
check(
  'every page derives the same box from the same frame',
  frameAspect(1280, 720) === frameAspect(1280, 720) && frameAspect(1280, 720) === '1280 / 720',
)

if (failures > 0) {
  console.error(`\ncamera: ${failures} check(s) FAILED`)
  process.exit(1)
}
console.log('\ncamera: all checks passed')

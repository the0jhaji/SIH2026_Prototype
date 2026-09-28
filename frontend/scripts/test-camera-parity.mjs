/**
 * Camera parity contract (frontend/src/views/*, components/CameraStage.tsx).
 * Runs on plain Node — no transform, no renderer, no dependencies.
 *
 *   npm run test:camera-parity
 *
 * `test:camera` guards the state half of the camera: one phase machine, so two
 * pages cannot disagree about whether the camera is running. This guards the
 * structural half, which is where Mission and Demo actually used to disagree.
 *
 * The bug, precisely: the camera *source* was never in question — one backend
 * producer, one `/api/camera/stream` connection — but the decisions *around* the
 * frame were made per page, and one page made a different one:
 *
 *   1. Mission locked its box to the frame aspect; Demo did not, so `cover`
 *      cropped the identical 1280x720 frame to whatever height the panel had.
 *   2. With the camera off, Demo drew a synthetic canvas in the camera slot
 *      instead of the shared placeholder — a second, fake picture of "the
 *      camera" that the rest of the app could not see.
 *   3. Demo omitted the hazard levels, so the same box was coloured differently.
 *   4. Both pages applied the fullscreen layer to two nested elements.
 *
 * Every one of those was a per-page decision, and per-page decisions are exactly
 * what silently comes back. These checks make the shared component the only
 * possible author of the camera picture: a second `getUserMedia`, a second
 * stream consumer, a per-page `aspect`/`fit`, or a fake feed in the camera slot
 * are all now visible as test failures rather than as a visual difference.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const SRC = join(ROOT, 'src')

let failures = 0

function check(name, condition, detail = '') {
  if (condition) {
    console.log(`  ok   ${name}`)
  } else {
    failures += 1
    console.error(`  FAIL ${name}${detail ? ` -- ${detail}` : ''}`)
  }
}

function sourceFiles(dir = SRC) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full))
    else if (/\.tsx?$/.test(entry)) out.push(full)
  }
  return out
}

const files = sourceFiles()
const read = f => readFileSync(f, 'utf8')
const rel = f => relative(SRC, f).replace(/\\/g, '/')

/** `name.ts:line` for every match, so a failure points straight at the code. */
function whereAll(files_, re) {
  const hits = []
  for (const f of files_) {
    read(f)
      .split('\n')
      .forEach((line, i) => {
        if (re.test(line)) hits.push(`${rel(f)}:${i + 1}`)
      })
  }
  return hits
}

const mission = read(join(SRC, 'views/MissionView.tsx'))
const demo = read(join(SRC, 'views/ExperimentsView.tsx'))
const cameraView = read(join(SRC, 'views/CameraView.tsx'))
const stage = read(join(SRC, 'components/CameraStage.tsx'))
const liveFeed = read(join(SRC, 'components/LiveFeed.tsx'))
const shell = read(join(SRC, 'views/AppShell.tsx'))
const domain = read(join(SRC, 'domain/camera.ts'))
const main = read(join(SRC, 'main.tsx'))

/** Only the view layer: the shared components are allowed to set these. */
const viewFiles = files.filter(f => f.includes(`${join('src', 'views')}`))

/** The prop names a view hands to a component, from its JSX call site. */
function propsOf(source, component) {
  const start = source.indexOf(`<${component}`)
  if (start < 0) return null
  const body = source.slice(start, source.indexOf('/>', start) + 2)
  return [...body.matchAll(/(\w+)=/g)].map(m => m[1]).filter(p => p !== 'key').sort()
}

console.log('one camera producer, consumed once')

// The backend already guarantees a single `CameraManager`; what the frontend
// must not do is open a second path to a device.
check(
  'no browser camera access anywhere (so no page can open a second device)',
  whereAll(files, /getUserMedia|mediaDevices|srcObject|MediaStreamTrack/).length === 0,
  whereAll(files, /getUserMedia|mediaDevices|srcObject|MediaStreamTrack/).join(', '),
)
check(
  'the stream endpoint is defined in exactly one place',
  whereAll(files, /CAMERA_STREAM_URL = '/).length === 1,
  whereAll(files, /CAMERA_STREAM_URL = '/).join(', '),
)
check(
  'exactly one component turns the stream URL into an element',
  whereAll(files, /streamUrl=\{CAMERA_STREAM_URL\}/).length === 1,
  whereAll(files, /streamUrl=\{CAMERA_STREAM_URL\}/).join(', '),
)
check(
  'exactly one image is fed by the stream, so one MJPEG connection per page',
  whereAll(files, /src=\{streamUrl\}/).length === 1,
  whereAll(files, /src=\{streamUrl\}/).join(', '),
)
check(
  'the camera controller is mounted once, above the router',
  whereAll(files, /^\s*<CameraProvider>/).length === 1 &&
    /<CameraProvider>[\s\S]*<App\s*\/>/.test(main),
  whereAll(files, /^\s*<CameraProvider>/).join(', '),
)

console.log('both pages consume the same component')

const missionProps = propsOf(mission, 'CameraStage')
const demoProps = propsOf(demo, 'CameraStage')
check('the Mission page mounts the shared stage', missionProps !== null)
check('the Demo page mounts the shared stage', demoProps !== null)
check(
  'both pages hand the stage the same props, so neither can render a different picture',
  JSON.stringify(missionProps) === JSON.stringify(demoProps),
  `mission=[${missionProps}] demo=[${demoProps}]`,
)
check(
  'no view chooses the box aspect for itself any more',
  whereAll(viewFiles, /\baspect=/).length === 0,
  whereAll(viewFiles, /\baspect=/).join(', '),
)
check(
  'the box aspect is derived from the served frame, in one shared function',
  /frameAspect/.test(stage) && /export function frameAspect/.test(domain),
)
check(
  'the frame falls back to 16:9 rather than to whatever the panel allows',
  /CAMERA_DEFAULT_ASPECT = '16 \/ 9'/.test(domain),
)
check(
  'the Camera page mounts the same shared viewport, not a camera of its own',
  /<CameraViewport/.test(cameraView) &&
    !/<img|getUserMedia|streamUrl=/.test(cameraView),
)
check(
  'the Camera page does not choose the box aspect either',
  !/\baspect=/.test(cameraView),
)

console.log('the frame is never cropped')

check(
  'the camera fits the frame inside its box, it does not crop to fill it',
  /fit="contain"/.test(stage) && !/fit="cover"/.test(stage),
)
check(
  'contain resolves to object-contain, so the letterbox is never a crop',
  /'absolute inset-0 h-full w-full object-contain'/.test(liveFeed),
)

console.log('no second, fake picture of the camera')

// The Demo page may still *illustrate* the procedure, but never in the camera
// slot: a synthetic canvas under a CAM-01 label is indistinguishable on screen
// from a real frame to anyone watching, which is the whole problem.
const demoPanel = demo.slice(demo.indexOf('title="Camera"'), demo.indexOf('title="AI Observation"'))
check(
  'the Demo camera panel always renders the shared stage',
  /<CameraStage/.test(demoPanel) && !/cameraRunning \? \(?\s*<CameraStage/.test(demoPanel),
)
check(
  'the canvas is confined to local simulator mode, labelled as an illustration',
  /mode === 'local' &&/.test(demoPanel) && /not a camera feed/.test(demoPanel),
)
check(
  'the Demo panel no longer swaps the feed out when the camera is off',
  !/cameraRunning \?[\s\S]{0,80}<CameraStage[\s\S]*?\) : \(/.test(demoPanel),
)
check(
  'both pages gate the overlay on the same live-camera condition',
  /detections=\{cameraRunning \?/.test(demo) && /detections = streamActive \?/.test(mission),
)
check(
  'the Demo page builds its overlay with the shared helpers, not its own copy',
  /hazardLevelsFrom/.test(demo) && /unattendedIdsFrom/.test(demo),
)
check(
  'the Demo page no longer carries a third copy of the camera transport',
  !/<CameraControls/.test(demo) && /<CameraControls/.test(stage),
)

console.log('mirroring')

// OpenCV hands out un-mirrored frames and the overlay divides by those same
// coordinates, so image and boxes agree. Mirroring one without the other would
// put every box on the wrong side of every object.
check(
  'nothing mirrors the feed or its overlay',
  whereAll(files, /scaleX\(-1\)|scale\(-1|-scale-x|rotateY\(180deg\)/).length === 0,
  whereAll(files, /scaleX\(-1\)|scale\(-1|-scale-x|rotateY\(180deg\)/).join(', '),
)
check(
  'the backend hands out un-mirrored frames',
  !/cv2\.flip|flip\(/.test(read(join(ROOT, '..', 'backend/camera/capture.py'))),
)

console.log('overlay alignment')

// Boxes are percentages of the *frame*, drawn inside a wrapper sized to the
// measured image rect. Never percentages of the browser viewport.
check(
  'boxes are mapped from the frame the backend reports, not the viewport',
  /buildOverlay/.test(liveFeed) && /clientWidth/.test(liveFeed) && !/window\.innerWidth/.test(liveFeed),
)
check(
  'the header frame size and the overlay frame size come from the same resolver',
  /resolveFrameSize/.test(demo) && /resolveFrameSize/.test(liveFeed),
)

console.log('lifecycle')

// Entering or leaving a page must not restart the camera, and fullscreen must be
// one layer rather than two nested fixed elements over the same image. Both
// components name the class, but exactly one of them can apply it: the viewport
// only when it is not already inside a host that took the screen.
check(
  'the fullscreen layer is applied by the host, and the nested viewport defers to it',
  /fullscreenHost && isFullscreen \? 'camera-viewport-fullscreen /.test(stage) &&
    /fullscreenHost=\{false\}/.test(stage),
)
check(
  'the two fullscreen application sites are mutually exclusive',
  /\$\{isFullscreen \? 'camera-viewport-fullscreen' : ''\}/.test(stage) &&
    /\$\{fullscreenHost && isFullscreen \? 'camera-viewport-fullscreen ' : ''\}/.test(stage),
)
check(
  'the fullscreen class is a real rule, and no camera class is dead',
  (read(join(SRC, 'index.css')).match(/^\s*\.camera-viewport-fullscreen \{/gm) ?? []).length === 1 &&
    whereAll(files, /['"`]camera-viewport['"`]/).length === 0,
  whereAll(files, /['"`]camera-viewport['"`]/).join(', '),
)
check(
  'the feed image is never unmounted by a camera phase change',
  /showFeed = streamActive/.test(stage) && !/streamActive \? <LiveCameraFeed/.test(stage),
)
check(
  'the transport is a sibling of the viewport, outside every phase branch',
  stage.indexOf('<CameraControls') > stage.indexOf('</CameraViewport>'),
)
check(
  'only one view is mounted at a time, so only one camera element exists',
  /view === 'mission' && <MissionView/.test(shell) && /\{view === 'experiments' && \(/.test(shell),
)

if (failures > 0) {
  console.error(`\ncamera-parity: ${failures} check(s) FAILED`)
  process.exit(1)
}
console.log('\ncamera-parity: all checks passed')

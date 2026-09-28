export type CameraStatus = 'disconnected' | 'connected' | 'error'

/** Mirror of the backend `CameraManager.info()` payload (camelCase JSON). */
export interface CameraInfo {
  status: CameraStatus
  running: boolean
  source: 'webcam' | 'mock' | 'none'
  cameraIndex: number
  width: number
  height: number
  fps: number
  mock: boolean
  frameCount: number
  error: string | null
}

/**
 * The one camera state machine the whole app agrees on.
 *
 * This replaces the ad-hoc booleans (`running`, `offline`, plus each view's own
 * idea of "stopped") that let the same physical camera read as CAMERA OFFLINE on
 * one page and CAMERA STOPPED on the next. `off` and `error` are deliberately
 * distinct: `off` is the operator's own decision and is recoverable by pressing
 * CAM ON, `error` is a backend/device failure and is *also* recoverable by
 * pressing CAM ON. `stale` means the camera is still running but has stopped
 * delivering frames — that is never treated as off, because the user did not
 * stop it.
 *
 * Camera phases say nothing about detection. A YOLO failure must never move the
 * camera out of `live`.
 */
export type CameraPhase = 'off' | 'starting' | 'live' | 'stopping' | 'error' | 'stale'

/** Everything a view may need, all derived from the single controller. */
export interface CameraViewState {
  phase: CameraPhase
  /** Backend reachable — a control can be sent. */
  available: boolean
  /** A frame is expected to be arriving right now (`live` or `stale`). */
  streamActive: boolean
  /** Epoch ms of the last status poll that saw a new frame; 0 if never. */
  lastFrameTime: number
  fps: number | null
  resolution: string | null
  errorMessage: string | null
  isFullscreen: boolean
  /** Raw backend payload, for the fields the UI mirrors verbatim. */
  info: CameraInfo | null
  /** Local-only: this build has no backend to talk to. */
  localMode: boolean
}

/**
 * THE camera state machine: one pure function from backend facts to one phase.
 *
 * It lives in the domain layer, beside the labels, rather than inside the React
 * provider, for two reasons. It is the thing every page displays, so it must not
 * be owned by the component that happens to be mounted; and as plain data it is
 * directly testable without a renderer (`npm run test:camera`).
 *
 * Because it is a pure function of its four inputs, two pages cannot disagree
 * about the same camera — there is nothing view-specific left to disagree about.
 *
 * `pendingPhase` carries the operator's in-flight intent, because the backend
 * answers `/api/camera/start` *before* the capture thread flips its flag: its own
 * response still says `running: false`, and trusting that is what made the UI
 * claim "no camera feed" for a whole poll interval while frames were already
 * being served.
 */
export function derivePhase(args: {
  info: CameraInfo | null
  reachable: boolean
  pendingPhase: CameraPhase | null
  frameStale: boolean
}): CameraPhase {
  const { info, reachable, pendingPhase, frameStale } = args
  if (pendingPhase) return pendingPhase
  // Unreachable is not "off". If it was running, the truth is that we stopped
  // hearing from it, which is staleness — a temporary condition the operator did
  // not cause and must not have to undo.
  if (!reachable) return info?.running ? 'stale' : 'off'
  if (!info) return 'off'
  if (info.status === 'error') return 'error'
  if (info.error) return 'error'
  if (!info.running) return 'off'
  return frameStale ? 'stale' : 'live'
}

export const CAMERA_STREAM_URL = '/api/camera/stream'

export const CAMERA_SNAPSHOT_URL = '/api/camera/snapshot'
export const CAMERA_POLL_MS = 2500

/**
 * The one canonical aspect ratio of the shared feed, derived from the frame size
 * the backend reports alongside the detections.
 *
 * This lives here, next to the stream URL, because the stream URL and the shape
 * of the picture are the same fact seen twice. Every camera surface takes its
 * aspect from this function rather than hardcoding `16 / 9`, so a camera that is
 * reconfigured to another size renders correctly everywhere at once.
 *
 * It is also what makes two pages show the *same* framing. The camera box has to
 * be locked to the frame's own shape: an unlocked box takes its height from the
 * surrounding panel, so a 1280x720 frame arriving at a box of any other shape
 * must either letterbox or be cropped, and the two pages then disagree about how
 * much of the picture the operator can see. `CAMERA_DEFAULT_ASPECT` is the value
 * used before any frame size is known — 1280x720 is the backend default
 * (`CAMERA_WIDTH`/`CAMERA_HEIGHT`).
 */
export const CAMERA_DEFAULT_ASPECT = '16 / 9'

export function frameAspect(
  frameWidth: number | null | undefined,
  frameHeight: number | null | undefined,
): string {
  if (typeof frameWidth !== 'number' || typeof frameHeight !== 'number') return CAMERA_DEFAULT_ASPECT
  if (!Number.isFinite(frameWidth) || !Number.isFinite(frameHeight)) return CAMERA_DEFAULT_ASPECT
  if (frameWidth <= 0 || frameHeight <= 0) return CAMERA_DEFAULT_ASPECT
  return `${Math.round(frameWidth)} / ${Math.round(frameHeight)}`
}

/**
 * How long a *running* camera may go without advancing its frame counter before
 * the UI calls the feed stale.
 *
 * Derived from frame liveness (`frameCount`), not from the poll interval: the
 * camera can be running perfectly while the last frame is a second old, and a
 * 30 FPS device must not be declared stale between two 2.5 s polls. Generous on
 * purpose — a false "stale" is a lie about a working camera, and the controls
 * stay visible either way, so the cost of being late is only a late label.
 */
export const CAMERA_STALE_MS = 6000

/**
 * The single vocabulary for camera status text.
 *
 * Every label the operator can see is defined here, so "CAMERA OFFLINE",
 * "CAMERA STOPPED", "STALE FEED", "NO CAMERA FEED" and "LIVE" cannot drift into
 * five different strings on five different pages.
 */
export const CAMERA_PHASE_LABEL: Record<CameraPhase, string> = {
  off: 'CAMERA STOPPED',
  starting: 'STARTING',
  live: 'LIVE',
  stopping: 'STOPPING',
  error: 'CAMERA ERROR',
  stale: 'STALE FEED',
}

export const CAMERA_PHASE_COLOR: Record<CameraPhase, string> = {
  off: '#94a3b8',
  starting: '#facc15',
  live: '#4ade80',
  stopping: '#facc15',
  error: '#f87171',
  stale: '#fbbf24',
}

/** The one-line explanation shown next to the controls. */
export function cameraPhaseHint(phase: CameraPhase, errorMessage: string | null): string {
  switch (phase) {
    case 'off':
      return 'Press CAM ON to start visual monitoring.'
    case 'starting':
      return 'Starting the camera…'
    case 'live':
      return 'Camera is streaming.'
    case 'stopping':
      return 'Stopping the camera…'
    case 'error':
      return errorMessage ?? 'The camera could not be started. Press CAM ON to retry.'
    case 'stale':
      return 'Waiting for camera frames…'
  }
}

/** Transport labels. Both buttons stay mounted; only their text and enabled
 *  state follow the phase, so a control can never vanish with the video. */
export const CAMERA_START_LABEL: Record<CameraPhase, string> = {
  off: 'CAM ON',
  starting: 'STARTING…',
  live: 'CAM ON',
  stopping: 'CAM ON',
  error: 'CAM ON',
  stale: 'CAM ON',
}

export const CAMERA_STOP_LABEL: Record<CameraPhase, string> = {
  off: 'CAM OFF',
  starting: 'CAM OFF',
  live: 'CAM OFF',
  stopping: 'STOPPING…',
  error: 'CAM OFF',
  stale: 'CAM OFF',
}

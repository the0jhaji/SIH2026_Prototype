import {
  CAMERA_PHASE_COLOR,
  CAMERA_PHASE_LABEL,
  CAMERA_START_LABEL,
  CAMERA_STOP_LABEL,
  cameraPhaseHint,
} from '../domain/camera'
import { useCamera } from '../hooks/cameraController'

/**
 * The one camera transport. Every view renders this; none of them write their
 * own.
 *
 * The structural guarantee the spec asks for: this component is a *sibling* of
 * the viewport, never a child of it, and it has no `videoFrame`/`running`
 * condition anywhere. It cannot be unmounted by a missing feed, a failed
 * detector, a stale frame, a route change or a fullscreen toggle, because
 * nothing it renders depends on any of those.
 *
 * Both buttons are always mounted. Only their label and enabled state follow the
 * phase, and the only reason either is ever disabled is a duplicate click while
 * a request is in flight. In particular CAM ON is NOT disabled when the backend
 * is unreachable: that is precisely the moment the operator needs to be able to
 * retry, and the old `disabled={... || offline}` made a transient poll failure
 * permanently strand the camera.
 */
export function CameraControls({ className = '' }: { className?: string }) {
  const { phase, pending, errorMessage, start, stop } = useCamera()

  const starting = phase === 'starting' || (pending && phase !== 'stopping')
  const stopping = phase === 'stopping'

  return (
    <div className={`shrink-0 ${className}`}>
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={start}
          disabled={starting}
          title="Start the camera"
          className="btn-primary px-3 py-1.5"
        >
          <span className="msym text-base leading-none">videocam</span>
          {CAMERA_START_LABEL[phase]}
        </button>
        <button
          type="button"
          onClick={stop}
          disabled={stopping || phase === 'off'}
          title="Stop the camera"
          className="btn-outline px-3 py-1.5"
        >
          <span className="msym text-base leading-none">videocam_off</span>
          {CAMERA_STOP_LABEL[phase]}
        </button>
      </div>

      {/* Status line. Always rendered so the phase is never ambiguous, and it
          reports the camera only — the AI engine has its own indicator. */}
      <div className="mt-1.5 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider">
        <span style={{ color: CAMERA_PHASE_COLOR[phase] }} className="flex items-center gap-1">
          <span
            aria-hidden
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ background: CAMERA_PHASE_COLOR[phase] }}
          />
          {CAMERA_PHASE_LABEL[phase]}
        </span>
        {errorMessage && phase === 'error' && (
          <span className="truncate normal-case text-red-300" title={errorMessage}>
            {errorMessage}
          </span>
        )}
      </div>
      <p className="mt-0.5 font-mono text-[10px] leading-snug text-on-surface-variant">
        {cameraPhaseHint(phase, errorMessage)}
      </p>
    </div>
  )
}

/**
 * Fullscreen toggle for the camera viewport.
 *
 * Deliberately *not* a second camera: it flips a flag in the canonical
 * controller and the viewport it belongs to expands in place. The same
 * `<img src="/api/camera/stream">` stays mounted, so there is one MJPEG
 * connection, no restart, and the overlay keeps its measured rect. ESC exits
 * (handled once, centrally, in the controller).
 */
export function CameraFullscreenToggle({ className = '' }: { className?: string }) {
  const { isFullscreen, toggleFullscreen } = useCamera()
  return (
    <button
      type="button"
      onClick={toggleFullscreen}
      title={isFullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen camera'}
      aria-pressed={isFullscreen}
      className={`btn-outline px-2 py-1 ${className}`}
    >
      <span className="msym text-base leading-none">{isFullscreen ? 'close_fullscreen' : 'fullscreen'}</span>
    </button>
  )
}

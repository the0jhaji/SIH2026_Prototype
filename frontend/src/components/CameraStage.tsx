import type { ReactNode } from 'react'
import { CAMERA_STREAM_URL, cameraPhaseHint, frameAspect } from '../domain/camera'
import type { Detection } from '../domain/detection'
import type { RiskLevel } from '../domain/safety'
import { LiveCameraFeed } from './LiveFeed'
import { CameraControls, CameraFullscreenToggle } from './CameraControls'
import { useCamera } from '../hooks/cameraController'
import { EmptyState } from '../views/ui'

/**
 * The video-or-placeholder surface, and the only place a camera `<img>` is
 * created.
 *
 * Every ASTRA page that shows the camera mounts this one component, so there is
 * exactly one `<img src="/api/camera/stream">` in the document at a time and
 * therefore exactly one MJPEG connection. Fullscreen works by swapping this
 * element's class — the `<img>` is never unmounted, so entering or leaving
 * fullscreen cannot restart the camera or drop a frame.
 */
export function CameraViewport({
  detections,
  unknownDetections,
  frameWidth,
  frameHeight,
  hazardLevels,
  unattendedIds,
  fill = false,
  aspect,
  compact = false,
  fullscreenHost = true,
}: {
  detections: Detection[]
  unknownDetections: Detection[]
  frameWidth: number | null
  frameHeight: number | null
  hazardLevels?: Record<string, RiskLevel> | null
  unattendedIds?: ReadonlySet<string> | null
  fill?: boolean
  /**
   * Escape hatch only. The box is normally locked to the shared feed's own
   * aspect (see `frameAspect`), so a view cannot accidentally render a different
   * framing from another page by forgetting to pass anything.
   */
  aspect?: string
  compact?: boolean
  /**
   * Whether this element is the element that goes `position: fixed` in
   * fullscreen. `CameraStage` passes `false` because its own wrapper already
   * takes the whole screen — viewport, transport and footer together — and two
   * nested fixed layers stacked a second viewport on top of the first.
   */
  fullscreenHost?: boolean
}) {
  const { phase, isFullscreen, streamActive, errorMessage } = useCamera()

  // `stale` keeps showing the last frame: the camera is still running, the feed
  // is just late. Only a stopped or errored camera shows the placeholder.
  const showFeed = streamActive
  const hint = cameraPhaseHint(phase, errorMessage)

  // One rule, applied identically on every page: the picture is locked to the
  // shape of the frame the backend is actually serving. This is what makes two
  // views of the same camera look the same.
  const frameBox = aspect ?? frameAspect(frameWidth, frameHeight)

  const placeholderTitle =
    phase === 'error'
      ? 'Camera error'
      : phase === 'off'
        ? 'Camera stopped'
        : phase === 'starting'
          ? 'Starting camera…'
          : phase === 'stopping'
            ? 'Stopping camera…'
            : 'No camera feed'

  return (
    <div
      className={`${fullscreenHost && isFullscreen ? 'camera-viewport-fullscreen ' : ''}${
        fill ? 'flex min-h-0 flex-1 flex-col' : 'flex flex-col'
      }`}
    >
      <div className={`relative ${fill ? 'min-h-0 flex-1' : ''}`}>
        {showFeed ? (
          <LiveCameraFeed
            streamUrl={CAMERA_STREAM_URL}
            detections={detections}
            unknownDetections={unknownDetections}
            frameWidth={frameWidth}
            frameHeight={frameHeight}
            hazardLevels={hazardLevels}
            unattendedIds={unattendedIds}
            fill={fill}
            fit="contain"
            aspect={frameBox}
          />
        ) : (
          /* The placeholder takes the same aspect as the live image, so pressing
             CAM ON does not change the shape of the panel. */
          <div
            className="w-full bg-black"
            style={{ aspectRatio: frameBox }}
          >
            <div className="flex h-full w-full items-center justify-center">
              <EmptyState
                icon="videocam_off"
                title={placeholderTitle}
                description={hint}
                compact={compact || !fill}
              />
            </div>
          </div>
        )}

        {showFeed && (
          /* Bottom-right, clear of the frame-size telemetry in the feed's own
             top-right corner. `pointer-events-auto` because the sibling overlay
             strips pointer events for the whole box. */
          <div className="absolute bottom-2 right-2 z-30">
            <CameraFullscreenToggle />
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * The shared camera block: a viewport and its transport, as siblings.
 *
 * This is the one camera surface every page mounts. It owns the viewport, the
 * transport and the fullscreen layer, so a page cannot pick a different frame,
 * a different framing or a second pair of CAM ON/OFF buttons — the divergence is
 * structurally impossible rather than merely discouraged.
 *
 * The controls sit *outside* the viewport element and outside every conditional
 * in it, which is what makes "the feed appears but the controls do not"
 * structurally impossible. `CameraStage` used to own its own pair of buttons and
 * a second copy lived in `CameraView`; both were driven by props that each view
 * computed separately, and they disagreed. There is now one control component
 * reading one controller.
 */
export function CameraStage({
  detections,
  unknownDetections,
  frameWidth,
  frameHeight,
  hazardLevels,
  unattendedIds,
  fill = false,
  aspect,
  footer,
}: {
  detections: Detection[]
  unknownDetections: Detection[]
  frameWidth: number | null
  frameHeight: number | null
  hazardLevels?: Record<string, RiskLevel> | null
  unattendedIds?: ReadonlySet<string> | null
  fill?: boolean
  aspect?: string
  footer?: ReactNode
}) {
  const { isFullscreen } = useCamera()

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${isFullscreen ? 'camera-viewport-fullscreen' : ''}`}>
      <CameraViewport
        detections={detections}
        unknownDetections={unknownDetections}
        frameWidth={frameWidth}
        frameHeight={frameHeight}
        hazardLevels={hazardLevels}
        unattendedIds={unattendedIds}
        fill={fill}
        aspect={aspect}
        fullscreenHost={false}
      />
      <CameraControls className="mt-2" />
      {footer}
    </div>
  )
}

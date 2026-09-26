import type { ReactNode } from 'react'
import { CAMERA_STREAM_URL, cameraPhaseHint } from '../domain/camera'
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
}: {
  detections: Detection[]
  unknownDetections: Detection[]
  frameWidth: number | null
  frameHeight: number | null
  hazardLevels?: Record<string, RiskLevel> | null
  unattendedIds?: ReadonlySet<string> | null
  fill?: boolean
  aspect?: string
  compact?: boolean
}) {
  const { phase, isFullscreen, streamActive, errorMessage } = useCamera()

  // `stale` keeps showing the last frame: the camera is still running, the feed
  // is just late. Only a stopped or errored camera shows the placeholder.
  const showFeed = streamActive
  const hint = cameraPhaseHint(phase, errorMessage)

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
      className={`camera-viewport ${isFullscreen ? 'camera-viewport-fullscreen' : ''} ${
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
            fit="cover"
            aspect={aspect}
          />
        ) : (
          /* The placeholder takes the same aspect as the live image, so pressing
             CAM ON does not change the shape of the panel. */
          <div
            className={`flex items-center justify-center bg-black ${
              aspect ? 'aspect-video w-full' : fill ? 'min-h-[12rem] w-full flex-1' : 'min-h-[12rem] w-full'
            }`}
            style={aspect ? { aspectRatio: aspect } : undefined}
          >
            <EmptyState
              icon="videocam_off"
              title={placeholderTitle}
              description={hint}
              compact={compact || !fill}
            />
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
      />
      <CameraControls className="mt-2" />
      {footer}
    </div>
  )
}

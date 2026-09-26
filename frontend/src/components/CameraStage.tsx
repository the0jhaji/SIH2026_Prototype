import type { ReactNode } from 'react'
import { CAMERA_STREAM_URL } from '../domain/camera'
import type { Detection } from '../domain/detection'
import type { RiskLevel } from '../domain/safety'
import { LiveCameraFeed } from './LiveFeed'
import { EmptyState } from '../views/ui'

/**
 * The live video surface plus its transport controls, shared by every view
 * that shows the camera.
 *
 * It exists because the live frame, the offline placeholder and the
 * CAM ON/OFF controls were duplicated verbatim in two views, and because
 * the camera is the one element allowed to claim leftover viewport height —
 * so the "fill" behaviour needs a single owner rather than a per-view
 * `max-h-[75vh]` guess.
 */
export function CameraStage({
  running,
  offline,
  detections,
  unknownDetections,
  frameWidth,
  frameHeight,
  hazardLevels,
  unattendedIds,
  fill = false,
  onStart,
  onStop,
  showControls = true,
  disabled = false,
  footer,
}: {
  running: boolean
  offline: boolean
  detections: Detection[]
  unknownDetections: Detection[]
  frameWidth: number | null
  frameHeight: number | null
  hazardLevels?: Record<string, RiskLevel> | null
  unattendedIds?: ReadonlySet<string> | null
  fill?: boolean
  onStart: () => void
  onStop: () => void
  showControls?: boolean
  disabled?: boolean
  footer?: ReactNode
}) {
  return (
    <div className={`flex flex-col ${fill ? 'min-h-0 flex-1' : ''}`}>
      {running ? (
        <LiveCameraFeed
          streamUrl={CAMERA_STREAM_URL}
          detections={detections}
          unknownDetections={unknownDetections}
          frameWidth={frameWidth}
          frameHeight={frameHeight}
          hazardLevels={hazardLevels}
          unattendedIds={unattendedIds}
          fill={fill}
        />
      ) : (
        <div className={`flex items-center justify-center bg-black ${fill ? 'min-h-0 flex-1' : 'aspect-video w-full'}`}>
          <EmptyState
            icon="videocam_off"
            title={offline ? 'Camera offline' : 'No camera feed'}
            description={
              offline
                ? 'The backend is not reachable, so no camera control is available.'
                : 'Press CAM ON to start the visual monitor. Nothing is inferred without a live frame.'
            }
            compact={!fill}
          />
        </div>
      )}

      {showControls && (
        <div className="mt-2 grid shrink-0 grid-cols-2 gap-2">
          <button
            type="button"
            onClick={onStart}
            disabled={disabled || running || offline}
            className="btn-primary px-3 py-1.5"
          >
            <span className="msym text-base leading-none">videocam</span>
            CAM ON
          </button>
          <button
            type="button"
            onClick={onStop}
            disabled={disabled || !running}
            className="btn-outline px-3 py-1.5"
          >
            <span className="msym text-base leading-none">videocam_off</span>
            CAM OFF
          </button>
        </div>
      )}

      {footer}
    </div>
  )
}

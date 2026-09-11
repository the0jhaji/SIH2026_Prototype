import { CAMERA_STREAM_URL } from '../domain/camera'
import { CLASS_COLOR, type DetectionResult, type DetectionStatus } from '../domain/detection'
import { LiveCameraFeed } from '../components/LiveFeed'
import { Empty, Panel, StatTile } from './ui'
import type { SafetyCommonProps } from './props'

interface Props extends SafetyCommonProps {
  detectionStatus: DetectionStatus | null
  detectionResult: DetectionResult | null
}

export function CameraView({
  cameraRunning,
  cameraOffline,
  onCameraStart,
  onCameraStop,
  detectionResult,
  detectionStatus,
}: Props) {
  const streamUrl = cameraRunning ? CAMERA_STREAM_URL : null
  const detections = cameraRunning ? detectionResult?.detections ?? [] : []
  const frameW = cameraRunning ? detectionResult?.frameWidth ?? null : null
  const frameH = cameraRunning ? detectionResult?.frameHeight ?? null : null

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
      <div className="space-y-4">
        <Panel
          title="Live Camera Feed"
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              CAM-01 · {cameraRunning ? 'LIVE' : 'STANDBY'}
            </span>
          }
        >
          {cameraRunning ? (
            <LiveCameraFeed
              streamUrl={streamUrl ?? ''}
              detections={detections}
              frameWidth={frameW}
              frameHeight={frameH}
            />
          ) : (
            <div className="flex aspect-video w-full items-center justify-center border border-outline-variant/30 bg-surface-container-low">
              <p className="font-mono text-xs uppercase tracking-widest text-on-surface-variant">
                {cameraOffline
                  ? 'CAMERA OFFLINE'
                  : 'No camera feed — press CAM ON to start the visual monitor'}
              </p>
            </div>
          )}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={onCameraStart}
              disabled={cameraRunning || cameraOffline}
              className="btn-primary"
            >
              CAM ON
            </button>
            <button
              type="button"
              onClick={onCameraStop}
              disabled={!cameraRunning}
              className="btn-outline"
            >
              CAM OFF
            </button>
          </div>
        </Panel>

        <Panel title="Detections">
          {detections.length === 0 ? (
            <Empty
              label={
                cameraRunning
                  ? 'No objects detected — waiting for recognition.'
                  : 'Camera offline. Nothing to interpret.'
              }
            />
          ) : (
            <ul className="mt-1 space-y-1.5">
              {detections.map((d, i) => (
                <li
                  key={`${d.timestamp}-${i}`}
                  className="flex items-center justify-between border border-outline-variant/30 bg-surface-container-low px-2.5 py-1.5"
                >
                  <span className="flex items-center gap-2 font-mono text-[11px] font-bold uppercase tracking-wider">
                    <span
                      className="h-2 w-2"
                      style={{ background: CLASS_COLOR[d.class_name] ?? '#4cd7f6' }}
                    />
                    {d.class_name.replace(/_/g, ' ')}
                  </span>
                  <span className="font-mono text-[11px] text-secondary">
                    {Math.round(d.confidence * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="space-y-4">
        <Panel title="Detection Engine">
          <div className="mt-1 grid grid-cols-2 gap-2">
            <StatTile label="Detector" value={detectionStatus?.detector ?? '—'} />
            <StatTile label="Enabled" value={detectionStatus?.enabled ? 'ON' : 'OFF'} />
            <StatTile label="Inference" value={detectionResult?.inferenceStatus ?? '—'} />
            <StatTile
              label="Latency"
              value={detectionResult?.inferenceMs != null ? `${detectionResult.inferenceMs}ms` : '—'}
            />
            <StatTile label="Objects" value={String(detections.length)} />
            <StatTile
              label="Raw/Stable"
              value={
                detectionStatus?.rawDetectionCount != null
                  ? `${detectionStatus.rawDetectionCount}/${detections.length}`
                  : '—'
              }
            />
            <StatTile
              label="Last"
              value={detectionStatus?.lastInference ? new Date(detectionStatus.lastInference).toLocaleTimeString() : '—'}
            />
          </div>
          {detectionStatus?.error && (
            <p className="mt-2 border border-error/40 bg-error/10 px-2 py-1 font-mono text-[11px] text-error">
              AI ENGINE ERROR: {detectionStatus.error}
            </p>
          )}
        </Panel>

        <Panel title="Model">
          <p className="mt-1 font-mono text-[11px] uppercase tracking-wider text-on-surface-variant">
            Weights
          </p>
          <p className="mb-2 break-all font-mono text-xs text-on-surface">
            {detectionStatus?.modelPath ?? 'no model loaded'}
          </p>
          {detectionStatus?.classes ? (
            <ul className="flex flex-wrap gap-1">
              {detectionStatus.classes.map(c => (
                <li
                  key={c}
                  className="border border-outline-variant/40 bg-surface-container-low px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-on-surface-variant"
                >
                  {c.replace(/_/g, ' ')}
                </li>
              ))}
            </ul>
          ) : (
            <Empty label="No class vocabulary (generic model)." />
          )}
        </Panel>
      </div>
    </div>
  )
}
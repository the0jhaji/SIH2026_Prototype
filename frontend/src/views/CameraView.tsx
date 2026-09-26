import { useMemo } from 'react'
import { CAMERA_STREAM_URL } from '../domain/camera'
import {
  BOX_COLORS,
  CLASS_COLOR,
  UNKNOWN_CLASS,
  hazardLevelsFrom,
  unattendedIdsFrom,
  type DetectionResult,
  type DetectionStatus,
} from '../domain/detection'
import { LiveCameraFeed } from '../components/LiveFeed'
import { Empty, Panel, StatTile } from './ui'
import type { SafetyCommonProps } from './props'

interface Props extends SafetyCommonProps {
  detectionStatus: DetectionStatus | null
  detectionResult: DetectionResult | null
}

const STATE_TONE: Record<string, string> = {
  UNATTENDED: 'text-error border-error/50 bg-error/10',
  RELEASED: 'text-warning border-warning/50 bg-warning/10',
  ATTENDED: 'text-tertiary border-outline-variant/40 bg-surface-container-low',
  OBJECT_INSIDE_BOX: 'text-primary border-primary/40 bg-primary/10',
}

function watchTone(state: string): string {
  return STATE_TONE[state] ?? 'text-on-surface-variant border-outline-variant/40 bg-surface-container-low'
}

export function CameraView({
  cameraRunning,
  cameraOffline,
  onCameraStart,
  onCameraStop,
  safety,
  detectionResult,
  detectionStatus,
  attendance,
}: Props) {
  const streamUrl = cameraRunning ? CAMERA_STREAM_URL : null
  // The unknown feed is a separate stream from the recognised one and is merged
  // only inside the overlay. It used to be dropped here entirely, which is why
  // unknown boxes never appeared on this view.
  const detections = cameraRunning ? detectionResult?.detections ?? [] : []
  const unknownDetections = cameraRunning ? detectionResult?.unknownDetections ?? [] : []
  const frameW = cameraRunning ? detectionResult?.frameWidth ?? null : null
  const frameH = cameraRunning ? detectionResult?.frameHeight ?? null : null
  const hazardLevels = useMemo(
    () => hazardLevelsFrom(safety.snapshot?.assessments),
    [safety.snapshot],
  )
  const unattendedIds = useMemo(
    () => unattendedIdsFrom(attendance?.result?.watches),
    [attendance],
  )
  const allDetections = [...detections, ...unknownDetections]

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
              unknownDetections={unknownDetections}
              frameWidth={frameW}
              frameHeight={frameH}
              hazardLevels={hazardLevels}
              unattendedIds={unattendedIds}
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

        <Panel
          title="Detections"
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {allDetections.length === 0
                ? 'IDLE'
                : `${detections.length} KNOWN · ${unknownDetections.length} UNKNOWN`}
            </span>
          }
        >
          {allDetections.length === 0 ? (
            <Empty
              label={
                cameraRunning
                  ? 'No objects detected — waiting for recognition.'
                  : 'Camera offline. Nothing to interpret.'
              }
            />
          ) : (
            <ul className="mt-1 space-y-1.5">
              {allDetections.map((d, i) => {
                const isUnknown = d.class_name === UNKNOWN_CLASS
                const isUnattended = isUnknown && unattendedIds.has(d.instance_id ?? '')
                return (
                  <li
                    key={`${d.instance_id ?? d.timestamp}-${i}`}
                    className={`flex items-center justify-between border px-2.5 py-1.5 ${
                      isUnattended
                        ? 'border-error/50 bg-error/10'
                        : 'border-outline-variant/30 bg-surface-container-low'
                    }`}
                  >
                    <span className="flex items-center gap-2 font-mono text-[11px] font-bold uppercase tracking-wider">
                      <span
                        className="h-2 w-2"
                        style={{
                          background: isUnattended
                            ? BOX_COLORS.unattended
                            : isUnknown
                              ? BOX_COLORS.unknown
                              : CLASS_COLOR[d.class_name] ?? '#4cd7f6',
                        }}
                      />
                      {isUnattended
                        ? 'unattended object'
                        : isUnknown
                          ? `unknown (${d.instance_id ?? '?'})`
                          : d.class_name.replace(/_/g, ' ')}
                    </span>
                    <span className="font-mono text-[11px] text-secondary">
                      {Math.round(d.confidence * 100)}%
                    </span>
                  </li>
                )
              })}
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
              label="Unknown"
              value={String(unknownDetections.length)}
              color={unknownDetections.length > 0 ? BOX_COLORS.unknown : undefined}
            />
            <StatTile
              label="Frame"
              value={
                detectionResult?.frameWidth && detectionResult?.frameHeight
                  ? `${detectionResult.frameWidth}x${detectionResult.frameHeight}`
                  : '—'
              }
            />
            <StatTile
              label="Raw/Stable"
              value={
                detectionStatus?.rawDetectionCount != null
                  ? `${detectionStatus.rawDetectionCount}/${detections.length}`
                  : '—'
              }
            />
            <StatTile
              label="AI Rate"
              value={
                detectionStatus?.actualFps != null
                  ? `${detectionStatus.actualFps.toFixed(1)}/${detectionStatus.targetFps ?? '—'} fps`
                  : '—'
              }
            />
            <StatTile
              label="Frames Dropped"
              value={detectionStatus?.skippedForRate != null ? String(detectionStatus.skippedForRate) : '—'}
            />
            <StatTile
              label="Trace"
              value={detectionStatus?.traceEnabled ? 'ON (verbose)' : 'OFF'}
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
          {detectionStatus?.generalPurpose === false && (
            <p className="mb-2 border border-warning/50 bg-warning/10 px-2 py-1 font-mono text-[11px] text-warning">
              SPECIALISED MODEL — {detectionStatus.classCount} classes only. It CANNOT
              detect person/bottle/cup/laptop. Set DETECTION_BACKEND=yolo for the
              general model.
            </p>
          )}
          <div className="mb-2 grid grid-cols-3 gap-2">
            <StatTile label="Classes" value={String(detectionStatus?.classCount ?? '—')} />
            <StatTile
              label="Size"
              value={detectionStatus?.modelSizeMb != null ? `${detectionStatus.modelSizeMb}MB` : '—'}
            />
            <StatTile label="imgsz" value={String(detectionStatus?.inputSize ?? '—')} />
            <StatTile label="conf" value={String(detectionStatus?.confThreshold ?? '—')} />
            <StatTile label="iou" value={String(detectionStatus?.iouThreshold ?? '—')} />
            <StatTile
              label="Role"
              value={
                detectionStatus?.generalPurpose === false
                  ? 'SPECIAL'
                  : detectionStatus?.generalPurpose
                    ? 'GENERAL'
                    : '—'
              }
            />
          </div>
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

        <Panel
          title="Object Containment & Attendance"
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {attendance.status?.objects != null
                ? `${attendance.status.objects} TRACKED · ${attendance.status.unattendedCount ?? 0} UNATTENDED`
                : 'IDLE'}
            </span>
          }
        >
          <div className="grid grid-cols-3 gap-2">
            <StatTile
              label="In Container"
              value={String(attendance.status?.inContainerCount ?? 0)}
            />
            <StatTile
              label="Unattended"
              value={String(attendance.status?.unattendedCount ?? 0)}
            />
            <StatTile
              label="Timeout"
              value={
                attendance.status?.thresholds?.unattendedTimeoutMs != null
                  ? `${(attendance.status.thresholds.unattendedTimeoutMs / 1000).toFixed(1)}s`
                  : '—'
              }
            />
          </div>

          {!cameraRunning ? (
            <Empty label="Camera offline — containment needs the live feed." />
          ) : (attendance.result?.watches ?? []).length === 0 ? (
            <Empty label="Tracking objects. Show an object near a container." />
          ) : (
            <ul className="mt-3 space-y-1.5">
              {(attendance.result?.watches ?? []).map(w => (
                <li
                  key={w.instanceId}
                  className={`border px-2.5 py-1.5 ${watchTone(w.state)}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] font-bold uppercase tracking-wider">
                      {w.className.replace(/_/g, ' ')}
                    </span>
                    <span className="font-mono text-[10px] uppercase tracking-wider">
                      {w.state.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[10px] opacity-80">
                    {w.insideContainer ? (
                      <span>
                        IN {w.containerClass?.replace(/_/g, ' ') ?? '?'} ·{' '}
                        {(w.containmentScore * 100).toFixed(0)}%
                      </span>
                    ) : null}
                    {!w.isUnknown && w.personFreeMs > 0 ? (
                      <span>NO CREW {Math.round(w.personFreeMs)}ms</span>
                    ) : null}
                    {w.isUnknown ? <span>UNKNOWN CLASS</span> : null}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {(attendance.result?.events ?? []).length > 0 && (
            <div className="mt-3">
              <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                Recent events
              </p>
              <ul className="space-y-1">
                {(attendance.result?.events ?? [])
                  .slice(-6)
                  .reverse()
                  .map(e => (
                    <li key={`${e.kind}-${e.ts}`} className="font-mono text-[10px] leading-snug">
                      <span className="text-on-surface-variant">
                        {new Date(e.ts).toLocaleTimeString()}
                      </span>{' '}
                      <span
                        className={
                          e.severity === 'warn'
                            ? 'text-warning'
                            : e.severity === 'error'
                              ? 'text-error'
                              : 'text-on-surface'
                        }
                      >
                        {e.kind.replace(/_/g, ' ')}
                      </span>
                      {e.object ? <span className="opacity-70"> · {e.object}</span> : null}
                      {e.reason ? <span className="opacity-60"> — {e.reason}</span> : null}
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
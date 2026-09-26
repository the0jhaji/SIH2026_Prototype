import { CAMERA_STREAM_URL } from '../domain/camera'
import { expectedStep } from '../domain/experiment'
import type { CameraInfo } from '../domain/camera'
import type { DetectionResult } from '../domain/detection'
import { BOX_COLORS, CLASS_COLOR, UNKNOWN_CLASS } from '../domain/detection'
import type { ExperimentMode } from '../hooks/useExperiment'
import type { ExperimentState } from '../domain/types'
import { LiveFeed } from '../components/LiveFeed'

interface Props {
  state: ExperimentState
  mode: ExperimentMode
  camera: CameraInfo | null
  cameraRunning: boolean
  cameraOffline: boolean
  onCameraStart: () => void
  onCameraStop: () => void
  detection: DetectionResult | null
}

export function LiveMonitorView({
  state,
  camera: _camera,
  cameraRunning,
  cameraOffline,
  onCameraStart,
  onCameraStop,
  detection,
}: Props) {
  const running = state.status === 'RUNNING'
  const expected = expectedStep(state.experiment, state.currentStepIndex)
  const streamUrl = cameraRunning ? CAMERA_STREAM_URL : null
  const detections = cameraRunning ? detection?.detections ?? [] : []
  const unknownDetections = cameraRunning ? detection?.unknownDetections ?? [] : []
  const detected = state.currentDetected
  const confidence = detected ? Math.round(detected.confidence * 100) : 0

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
      <div className="space-y-4">
        <section className="panel relative p-0">
          <div className="flex items-center justify-between border-b border-outline-variant/40 px-4 py-2">
            <h2 className="heading-title">Live Camera Feed</h2>
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              CAM-01 · {cameraRunning ? 'LIVE' : 'STANDBY'}
            </span>
          </div>
          <div className="p-4">
            <LiveFeed
              state={state}
              streamUrl={streamUrl}
              detections={detections}
              unknownDetections={unknownDetections}
              frameWidth={cameraRunning ? detection?.frameWidth ?? null : null}
              frameHeight={cameraRunning ? detection?.frameHeight ?? null : null}
            />
          </div>

          <div className="border-t border-outline-variant/40 bg-surface-container-low px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
                  Astra interpreting
                </span>
                <span className="font-mono text-sm font-bold text-primary">
                  {detected?.activity?.replace(/_/g, ' ') ?? '—'}
                </span>
                <span className="font-mono text-sm text-secondary">{confidence}%</span>
              </div>
              <div className="flex h-2 w-40 overflow-hidden bg-surface-container-high">
                <div
                  className={`h-full transition-all ${
                    confidence >= 80 ? 'bg-primary' : confidence >= 50 ? 'bg-secondary' : 'bg-error'
                  }`}
                  style={{ width: `${confidence}%` }}
                />
              </div>
            </div>
            {expected && running && (
              <p className="mt-2 font-mono text-[11px] uppercase tracking-wider text-on-surface-variant">
                Expected next: <span className="text-secondary">{expected.label}</span>
              </p>
            )}
          </div>
        </section>

        <section className="panel p-4">
          <div className="flex items-center justify-between">
            <h2 className="heading-title">Astra Voice</h2>
            <span className="chip border-primary/50 bg-primary/10 text-primary">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
              ONLINE
            </span>
          </div>
          <div className="mt-4 flex items-end gap-1">
            <Waveform />
          </div>
          <p className="mt-3 font-mono text-xs text-on-surface-variant">
            {state.lastClassification?.voice
              ? `“${state.lastClassification.voice}”`
              : 'Listening for operator actions…'}
          </p>
        </section>
      </div>

      <div className="space-y-4">
        <section className="panel p-4">
          <h2 className="heading-title">Detections</h2>
          {detections.length === 0 && unknownDetections.length === 0 ? (
            <p className="mt-3 font-mono text-[11px] text-on-surface-variant">
              No objects detected{cameraRunning ? ' — waiting for recognition' : ' — camera offline'}.
            </p>
          ) : (
            <ul className="mt-3 space-y-1.5">
              {[...detections, ...unknownDetections].map((d, i) => (
                <li
                  key={i}
                  className="flex items-center justify-between border border-outline-variant/30 bg-surface-container-low px-2.5 py-1.5"
                >
                  <span className="flex items-center gap-2 font-mono text-[11px] font-bold uppercase tracking-wider">
                    <span
                      className="h-2 w-2"
                      style={{
                        background:
                          d.class_name === UNKNOWN_CLASS
                            ? BOX_COLORS.unknown
                            : CLASS_COLOR[d.class_name] ?? '#4cd7f6',
                      }}
                    />
                    {d.class_name === UNKNOWN_CLASS
                      ? `unknown (${d.instance_id ?? '?'})`
                      : d.class_name.replace(/_/g, ' ')}
                  </span>
                  <span className="font-mono text-[11px] text-secondary">
                    {Math.round(d.confidence * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-4 grid grid-cols-2 gap-2">
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
        </section>

        <section className="panel p-4">
          <h2 className="heading-title">Detection Engine</h2>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Tile label="Enabled" value={detection?.enabled ? 'ON' : 'OFF'} />
            <Tile label="Objects" value={String(detection?.detections?.length ?? 0)} />
            <Tile label="Inference" value={detection?.inferenceStatus ?? '—'} />
            <Tile label="Latency" value={detection?.inferenceMs != null ? `${detection.inferenceMs}ms` : '—'} />
            <Tile label="Unknown" value={String(detection?.unknownDetections?.length ?? 0)} />
          </div>
        </section>
      </div>
    </div>
  )
}

const BARS = [6, 10, 4, 12, 8, 14, 5, 9, 11, 7, 3, 12, 8, 13, 6, 10, 4, 9, 7, 12]

function Waveform() {
  return (
    <div className="flex h-10 w-full items-end gap-0.5">
      {BARS.map((b, i) => (
        <div
          key={i}
          className="w-full bg-primary/70"
          style={{
            height: `${b * 6}%`,
            animation: `wave 0.9s ease-in-out infinite`,
            animationDelay: `${i * 45}ms`,
          }}
        />
      ))}
    </div>
  )
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="tile px-2 py-1.5 text-center">
      <p className="overline-label">{label}</p>
      <p className="copy-value">{value}</p>
    </div>
  )
}

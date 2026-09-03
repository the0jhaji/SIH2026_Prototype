import type { CameraInfo } from '../domain/camera'
import type { DetectionResult, DetectionStatus } from '../domain/detection'
import type { ExperimentState } from '../domain/types'

interface Props {
  state: ExperimentState
  camera: CameraInfo | null
  cameraOffline: boolean
  detection: DetectionResult | null
  detectionStatus: DetectionStatus | null
  detectionOffline: boolean
}

export function AnalyticsView({
  state,
  camera,
  cameraOffline,
  detection,
  detectionStatus,
  detectionOffline,
}: Props) {
  const camRunning = camera?.running === true && !cameraOffline
  const inferenceOk = detectionStatus?.inferenceStatus === 'ok' && !detectionOffline
  const detections = detection?.detections ?? []
  const lastLatency = detection?.inferenceMs
  const confidence = state.currentDetected ? Math.round(state.currentDetected.confidence * 100) : 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        <StatCard label="Inference status" value={inferenceOk ? 'OK' : (detectionStatus?.inferenceStatus ?? 'OFF')} accent={inferenceOk ? 'primary' : 'secondary'} />
        <StatCard label="Frames / sec" value={camRunning ? String(camera?.fps ?? '—') : '—'} accent="primary" />
        <StatCard label="Latency" value={lastLatency != null ? `${lastLatency}ms` : '—'} accent="tertiary" />
        <StatCard label="Detections" value={String(detections.length)} accent="secondary" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel p-4">
          <h2 className="heading-title">Model Card</h2>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Tile label="Backend" value={detectionStatus?.detector ?? '—'} />
            <Tile label="Classes" value={String(detectionStatus?.classes?.length ?? 0)} />
            <Tile
              label="Weights"
              value={detectionStatus?.modelLoaded ? 'LOADED' : 'MISSING'}
            />
            <Tile
              label="Inference mode"
              value={detectionStatus?.enabled ? 'ON' : 'OFF'}
            />
          </div>
        </section>

        <section className="panel p-4">
          <h2 className="heading-title">Object Workload</h2>
          <div className="mt-3 space-y-2">
            {detections.length === 0 ? (
              <p className="font-mono text-[11px] text-on-surface-variant">
                No objects in current frame.
              </p>
            ) : (
              detections.map((d, i) => (
                <div key={i} className="flex items-center gap-3">
                  <span className="w-32 truncate font-mono text-[11px] font-bold uppercase tracking-wider">
                    {d.class_name.replace(/_/g, ' ')}
                  </span>
                  <div className="h-1.5 flex-1 bg-surface-container-high">
                    <div
                      className="h-full bg-primary"
                      style={{ width: `${Math.round(d.confidence * 100)}%` }}
                    />
                  </div>
                  <span className="w-10 text-right font-mono text-[11px] text-secondary">
                    {Math.round(d.confidence * 100)}%
                  </span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel p-4">
          <h2 className="heading-title">Confidence</h2>
          <div className="mt-4 flex items-end gap-3">
            <div className="text-5xl font-bold tabular-nums text-primary">{confidence}%</div>
            <div className="flex-1">
              <div className="h-3 w-full bg-surface-container-high">
                <div
                  className={`h-full ${confidence >= 80 ? 'bg-primary' : confidence >= 50 ? 'bg-secondary' : 'bg-error'}`}
                  style={{ width: `${confidence}%` }}
                />
              </div>
              <p className="mt-1 font-mono text-[9px] uppercase tracking-widest text-on-surface-variant">
                Current detection
              </p>
            </div>
          </div>
        </section>

        <section className="panel p-4">
          <h2 className="heading-title">Latency (last frame)</h2>
          <div className="mt-4 flex items-end gap-3">
            <div className="text-5xl font-bold tabular-nums text-secondary">
              {lastLatency != null ? lastLatency : '—'}
              <span className="text-xl text-on-surface-variant">ms</span>
            </div>
            <p className="pb-1 font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              inference per frame
            </p>
          </div>
        </section>
      </div>
    </div>
  )
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent: 'primary' | 'secondary' | 'tertiary'
}) {
  const color = { primary: 'text-primary', secondary: 'text-secondary', tertiary: 'text-tertiary' }[accent]
  return (
    <div className="panel p-3">
      <p className="overline-label">{label}</p>
      <p className={`mt-1 font-mono text-2xl font-bold tabular-nums ${color}`}>{value}</p>
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

import { CAMERA_STREAM_URL } from '../domain/camera'
import { expectedStep } from '../domain/experiment'
import type { CameraInfo } from '../domain/camera'
import type { DetectionResult } from '../domain/detection'
import type { ExperimentMode } from '../hooks/useExperiment'
import type { ExperimentState } from '../domain/types'
import { LiveFeed } from '../components/LiveFeed'

interface Props {
  state: ExperimentState
  mode: ExperimentMode
  camera: CameraInfo | null
  cameraRunning: boolean
  cameraSending: boolean
  cameraOffline: boolean
  onCameraStart: () => void
  onCameraStop: () => void
  detection: DetectionResult | null
  connected: boolean
  busy: boolean
  onStart: () => void
  onStop: () => void
}

const ACTION_LABEL: Record<string, string> = {
  PICK: 'Pick',
  PLACE: 'Place',
  OPEN: 'Open',
}

export function ExperimentsView({
  state,
  mode,
  camera: _camera,
  cameraRunning,
  cameraSending,
  cameraOffline,
  onCameraStart,
  onCameraStop,
  detection,
  connected,
  busy,
  onStart,
  onStop,
}: Props) {
  const running = state.status === 'RUNNING'
  const expected = expectedStep(state.experiment, state.currentStepIndex)
  const streamUrl = cameraRunning ? CAMERA_STREAM_URL : null
  const cameraDisabled = mode !== 'backend' || cameraSending || cameraOffline

  const protocolCards = [
    { id: 'ACTIVE', label: 'ACTIVE', sub: 'Loaded protocol', icon: 'science', active: true },
    { id: 'DRAFT', label: 'DRAFT', sub: 'Uncommitted changes', icon: 'edit_note', active: false },
    { id: 'ARCHIVE', label: 'ARCHIVE', sub: 'Previous runs', icon: 'inventory_2', active: false },
  ]

  return (
    <div className="grid gap-4 lg:grid-cols-[15rem_1fr]">
      {/* Protocol list */}
      <section className="panel p-3">
        <h2 className="heading-title">Protocols</h2>
        <div className="mt-3 space-y-2">
          {protocolCards.map(card => (
            <button
              key={card.id}
              type="button"
              className={`flex w-full items-center gap-2 border px-2.5 py-2 text-left transition ${
                card.active
                  ? 'border-primary/70 bg-primary/10 text-on-surface'
                  : 'border-outline-variant/40 bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'
              }`}
            >
              <span className="msym text-xl leading-none">{card.icon}</span>
              <span className="min-w-0">
                <span className="block font-mono text-[11px] font-bold uppercase tracking-wider">
                  {card.label}
                </span>
                <span className="block truncate font-mono text-[9px] text-on-surface-variant">
                  {card.sub}
                </span>
              </span>
            </button>
          ))}
        </div>
      </section>

      {/* Details + procedure + camera */}
      <div className="space-y-4">
        <section className="panel p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="heading-title">Protocol</h2>
              <h1 className="mt-1 truncate font-sans text-2xl font-bold tracking-tight text-on-surface">
                {state.experiment.name}
              </h1>
              <p className="mt-1 max-w-2xl text-sm text-on-surface-variant">
                {state.experiment.description}
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1.5">
              <span className="chip border-primary/60 bg-primary/10 text-primary">
                <span className={`h-1.5 w-1.5 rounded-full ${running ? 'animate-pulse bg-primary' : 'bg-outline'}`} />
                {state.status}
              </span>
              {state.recording && (
                <span className="chip border-error/60 bg-error-container/20 text-error">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-error" />
                  REC
                </span>
              )}
            </div>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2">
            <Tile label="Steps" value={String(state.experiment.steps.length)} />
            <Tile label="Completed" value={String(state.completedStepIds.length)} />
            <Tile label="Source" value={mode === 'backend' ? 'Backend · FastAPI' : 'Local simulator'} />
          </div>
        </section>

        <section className="panel p-4">
          <div className="flex items-center justify-between">
            <h2 className="heading-title">Session Media</h2>
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={onCameraStart}
                disabled={cameraDisabled || cameraRunning}
                className="btn-ghost"
              >
                <span className="msym text-lg leading-none">videocam</span>
                CAM-01 ON
              </button>
              <button
                type="button"
                onClick={onCameraStop}
                disabled={cameraDisabled || !cameraRunning}
                className="btn-ghost"
              >
                <span className="msym text-lg leading-none">videocam_off</span>
                OFF
              </button>
            </div>
          </div>

          <div className="mt-3">
            <LiveFeed
              state={state}
              streamUrl={streamUrl}
              detections={cameraRunning ? detection?.detections ?? [] : []}
              frameWidth={cameraRunning ? detection?.frameWidth ?? null : null}
              frameHeight={cameraRunning ? detection?.frameHeight ?? null : null}
            />
          </div>

          {cameraOffline && mode === 'backend' && (
            <p className="mt-2 font-mono text-[11px] text-secondary">
              Backend unreachable — camera controls unavailable.
            </p>
          )}
        </section>

        <section className="panel p-4">
          <h2 className="heading-title">Procedure</h2>
          <ol className="mt-3 space-y-1.5">
            {state.experiment.steps.map((step, i) => {
              const done = state.completedStepIds.includes(step.id)
              const current = running && expected?.id === step.id
              return (
                <li
                  key={step.id}
                  className={`flex items-center gap-3 border px-3 py-2 ${
                    done
                      ? 'border-secondary/50 bg-secondary/10 text-on-surface'
                      : current
                        ? 'border-primary/70 bg-primary/10 text-on-surface'
                        : 'border-outline-variant/30 bg-surface-container-low text-on-surface-variant'
                  }`}
                >
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center font-mono text-[11px] font-bold ${
                      done
                        ? 'bg-secondary text-black'
                        : current
                          ? 'bg-primary text-black'
                          : 'border border-outline-variant/50'
                    }`}
                  >
                    {done ? '✓' : i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-sans text-sm font-medium">{step.label}</p>
                    <p className="font-mono text-[9px] uppercase tracking-widest text-on-surface-variant">
                      {ACTION_LABEL[step.action ?? ''] ?? step.action} · {step.activity}
                    </p>
                  </div>
                  {current && (
                    <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-primary">
                      Next ▸
                    </span>
                  )}
                </li>
              )
            })}
          </ol>

          <div className="mt-4 flex items-center gap-3 border-t border-outline-variant/40 pt-4">
            <button
              type="button"
              onClick={onStart}
              disabled={mode === 'backend' ? !connected || running || busy : running || busy}
              className="btn-primary"
            >
              <span className="msym text-lg leading-none">rocket_launch</span>
              {running ? 'Running…' : 'Start Experiment'}
            </button>
            <button
              type="button"
              onClick={onStop}
              disabled={!running || busy}
              className="btn-outline"
            >
              <span className="msym text-lg leading-none">stop</span>
              Stop
            </button>
            {mode === 'backend' && !connected && (
              <span className="font-mono text-[10px] uppercase tracking-wider text-secondary">
                Backend offline
              </span>
            )}
          </div>
        </section>
      </div>
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

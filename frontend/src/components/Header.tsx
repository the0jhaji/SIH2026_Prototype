import type { ExperimentMode } from '../hooks/useExperiment'
import type { ExperimentState } from '../domain/types'
import { RecordingBadge, StatusBadge } from './badges'

interface Props {
  state: ExperimentState
  mode: ExperimentMode
  connected: boolean
  busy: boolean
  onStart: () => void
  onStop: () => void
  onModeChange: (mode: ExperimentMode) => void
}

export function Header({
  state,
  mode,
  connected,
  busy,
  onStart,
  onStop,
  onModeChange,
}: Props) {
  const running = state.status === 'RUNNING'
  const canStart = mode === 'local' ? !running : connected && !running
  const offline = mode === 'backend' && !connected

  return (
    <header className="border-b border-slate-800/80 bg-slate-950/60 px-5 py-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-700 bg-gradient-to-b from-slate-800 to-slate-900 font-mono text-lg text-emerald-400">
            ✦
          </div>
          <div>
            <h1 className="text-base font-bold leading-tight text-slate-100">BAS-AI</h1>
            <p className="text-[11px] leading-tight text-slate-500">
              On-board experiment assistant · SIH 2026 PS 26174
            </p>
          </div>
        </div>

        <div className="min-w-[10rem]">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-slate-200">{state.experiment.name}</p>
            <StatusBadge status={state.status} />
            <RecordingBadge recording={state.recording} />
          </div>
          <p className="mt-0.5 text-[11px] text-slate-500">{state.experiment.description}</p>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <div
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
              mode === 'local'
                ? 'border-slate-600/60 bg-slate-800/60 text-slate-400'
                : connected
                  ? 'border-emerald-500/50 bg-emerald-950/60 text-emerald-300'
                  : 'border-rose-500/50 bg-rose-950/60 text-rose-300'
            }`}
            title={mode === 'local' ? 'Local simulation mode' : 'WebSocket connection to backend'}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                mode === 'local'
                  ? 'bg-slate-500'
                  : connected
                    ? 'animate-pulse bg-emerald-400'
                    : 'bg-rose-500'
              }`}
            />
            {mode === 'local' ? 'LOCAL' : connected ? 'ONLINE' : 'OFFLINE'}
          </div>

          <label className="sr-only" htmlFor="source-select">
            Perception source
          </label>
          <select
            id="source-select"
            value={mode}
            onChange={event => onModeChange(event.target.value as ExperimentMode)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs font-medium text-slate-300 focus:border-emerald-500 focus:outline-none"
          >
            <option value="backend">Backend · FastAPI</option>
            <option value="local">Local simulator</option>
          </select>

          <button
            type="button"
            onClick={onStart}
            disabled={!canStart || busy}
            className="rounded-lg border border-emerald-500/50 bg-emerald-600/20 px-4 py-1.5 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-600/30 disabled:cursor-not-allowed disabled:opacity-40"
            title={offline ? 'Backend offline — start the FastAPI server' : undefined}
          >
            Start experiment
          </button>
          <button
            type="button"
            onClick={onStop}
            disabled={!running || busy}
            className="rounded-lg border border-rose-500/50 bg-rose-600/20 px-4 py-1.5 text-sm font-semibold text-rose-300 transition hover:bg-rose-600/30 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Stop
          </button>
        </div>
      </div>
    </header>
  )
}
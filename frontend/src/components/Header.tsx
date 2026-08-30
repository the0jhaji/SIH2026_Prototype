import type { ExperimentMode } from '../hooks/useExperiment'
import type { ExperimentState } from '../domain/types'
import { useTheme } from '../hooks/useTheme'
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
  const { theme, toggle } = useTheme()

  return (
    <header className="border-b border-slate-200 bg-white/70 px-5 py-3 dark:border-slate-800/80 dark:bg-slate-950/60">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-300 bg-gradient-to-b from-slate-200 to-slate-300 font-mono text-lg text-emerald-600 dark:border-slate-700 dark:from-slate-800 dark:to-slate-900 dark:text-emerald-400">
            ✦
          </div>
          <div>
            <h1 className="text-base font-bold leading-tight text-slate-900 dark:text-slate-100">Astra AI</h1>
            <p className="text-[11px] leading-tight text-slate-500">
              On-board experiment assistant · SIH 2026 PS 26174
            </p>
          </div>
        </div>

        <div className="min-w-[10rem]">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{state.experiment.name}</p>
            <StatusBadge status={state.status} />
            <RecordingBadge recording={state.recording} />
          </div>
          <p className="mt-0.5 text-[11px] text-slate-500">{state.experiment.description}</p>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <div
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
              mode === 'local'
                ? 'border-slate-400/60 bg-slate-200/70 text-slate-600 dark:border-slate-600/60 dark:bg-slate-800/60 dark:text-slate-400'
                : connected
                  ? 'border-emerald-500/50 bg-emerald-100/70 text-emerald-700 dark:border-emerald-500/50 dark:bg-emerald-950/60 dark:text-emerald-300'
                  : 'border-rose-500/50 bg-rose-100/70 text-rose-700 dark:border-rose-500/50 dark:bg-rose-950/60 dark:text-rose-300'
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
            className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-medium text-slate-700 focus:border-emerald-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
          >
            <option value="backend">Backend · FastAPI</option>
            <option value="local">Local simulator</option>
          </select>

          <button
            type="button"
            onClick={toggle}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          >
            {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>

          <button
            type="button"
            onClick={onStart}
            disabled={!canStart || busy}
            className="rounded-lg border border-emerald-600/60 bg-emerald-100 px-4 py-1.5 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-40 dark:border-emerald-500/50 dark:bg-emerald-600/20 dark:text-emerald-300 dark:hover:bg-emerald-600/30"
            title={offline ? 'Backend offline — start the FastAPI server' : undefined}
          >
            Start experiment
          </button>
          <button
            type="button"
            onClick={onStop}
            disabled={!running || busy}
            className="rounded-lg border border-rose-600/60 bg-rose-100 px-4 py-1.5 text-sm font-semibold text-rose-700 transition hover:bg-rose-200 disabled:cursor-not-allowed disabled:opacity-40 dark:border-rose-500/50 dark:bg-rose-600/20 dark:text-rose-300 dark:hover:bg-rose-600/30"
          >
            Stop
          </button>
        </div>
      </div>
    </header>
  )
}
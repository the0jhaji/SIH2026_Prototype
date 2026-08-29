import type { ExperimentState } from '../domain/types'
import { RecordingBadge, StatusBadge } from './badges'

interface Props {
  state: ExperimentState
  onStart: () => void
  onStop: () => void
}

export function Header({ state, onStart, onStop }: Props) {
  const running = state.status === 'RUNNING'
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
          <button
            type="button"
            onClick={onStart}
            disabled={running}
            className="rounded-lg border border-emerald-500/50 bg-emerald-600/20 px-4 py-1.5 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-600/30 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Start experiment
          </button>
          <button
            type="button"
            onClick={onStop}
            disabled={!running}
            className="rounded-lg border border-rose-500/50 bg-rose-600/20 px-4 py-1.5 text-sm font-semibold text-rose-300 transition hover:bg-rose-600/30 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Stop
          </button>
        </div>
      </div>
    </header>
  )
}
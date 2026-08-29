import type { ExperimentStatus } from '../domain/types'

const STATUS_STYLE: Record<ExperimentStatus, string> = {
  IDLE: 'bg-slate-700/60 text-slate-200 border-slate-500/40',
  RUNNING: 'bg-emerald-950/60 text-emerald-300 border-emerald-500/40',
  STOPPED: 'bg-amber-950/60 text-amber-300 border-amber-500/40',
  COMPLETED: 'bg-sky-950/60 text-sky-300 border-sky-500/40',
}

export function StatusBadge({ status }: { status: ExperimentStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide ${STATUS_STYLE[status]}`}
    >
      {status === 'RUNNING' && (
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
        </span>
      )}
      {status}
    </span>
  )
}

export function RecordingBadge({ recording }: { recording: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide ${
        recording
          ? 'border-rose-500/50 bg-rose-950/50 text-rose-300'
          : 'border-slate-600/60 bg-slate-800/60 text-slate-400'
      }`}
    >
      <span
        className={`h-2 w-2 rounded-full ${recording ? 'animate-pulse bg-rose-500' : 'bg-slate-500'}`}
      />
      {recording ? 'REC' : 'NOT REC'}
    </span>
  )
}
import type { CameraInfo, CameraStatus } from '../domain/camera'
import type { ExperimentMode } from '../hooks/useExperiment'

const STATUS_STYLE: Record<CameraStatus, string> = {
  connected: 'border-emerald-500/50 bg-emerald-950/60 text-emerald-300',
  disconnected: 'border-slate-600/60 bg-slate-800/60 text-slate-400',
  error: 'border-rose-500/50 bg-rose-950/60 text-rose-300',
}

const STATUS_LABEL: Record<CameraStatus, string> = {
  connected: 'CAMERA CONNECTED',
  disconnected: 'CAMERA DISCONNECTED',
  error: 'CAMERA ERROR',
}

interface Props {
  mode: ExperimentMode
  info: CameraInfo | null
  offline: boolean
  sending: boolean
  onStart: () => void
  onStop: () => void
}

export function CameraPanel({ mode, info, offline, sending, onStart, onStop }: Props) {
  const backendActive = mode === 'backend'
  const status: CameraStatus = !backendActive || offline || !info ? 'disconnected' : info.status
  const running = backendActive && info?.running === true
  const disabled = !backendActive || sending || offline

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Camera</h2>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide ${STATUS_STYLE[status]}`}
        >
          {running && (
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>
          )}
          {STATUS_LABEL[status]}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-md bg-slate-800/60 px-2 py-1.5">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Source</p>
          <p className="font-mono text-sm font-semibold text-slate-200">
            {info ? info.source : '—'}
          </p>
        </div>
        <div className="rounded-md bg-slate-800/60 px-2 py-1.5">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Resolution</p>
          <p className="font-mono text-sm font-semibold text-slate-200">
            {info ? `${info.width}×${info.height}` : '—'}
          </p>
        </div>
        <div className="rounded-md bg-slate-800/60 px-2 py-1.5">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Frames</p>
          <p className="font-mono text-sm font-semibold text-slate-200">
            {info ? String(info.frameCount) : '—'}
          </p>
        </div>
      </div>

      {info?.error && (
        <p className="mt-2 text-xs text-rose-300">{(info.error as string) ?? ''}</p>
      )}
      {offline && (
        <p className="mt-2 text-xs text-amber-300">Backend unreachable — camera controls unavailable.</p>
      )}
      {mode !== 'backend' && (
        <p className="mt-2 text-xs text-slate-500">Camera runs through the backend; switch to Backend mode.</p>
      )}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onStart}
          disabled={disabled || running}
          className="rounded-lg border border-emerald-500/50 bg-emerald-600/20 px-4 py-1.5 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-600/30 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Start camera
        </button>
        <button
          type="button"
          onClick={onStop}
          disabled={disabled || !running}
          className="rounded-lg border border-rose-500/50 bg-rose-600/20 px-4 py-1.5 text-sm font-semibold text-rose-300 transition hover:bg-rose-600/30 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Stop camera
        </button>
      </div>
    </section>
  )
}
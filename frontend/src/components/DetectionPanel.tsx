import type { DetectionResult, DetectionStatus } from '../domain/detection'

function ago(ms: number | null): string {
  if (ms == null) return 'never'
  const seconds = Math.max(0, Math.round((Date.now() - ms) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  return `${Math.round(seconds / 60)}m ago`
}

interface Props {
  status: DetectionStatus | null
  result: DetectionResult | null
  offline: boolean
  cameraRunning: boolean
}

const STATUS_CHIP: Record<string, string> = {
  disabled: 'border-slate-600/60 bg-slate-800/60 text-slate-400',
  idle: 'border-amber-500/50 bg-amber-950/60 text-amber-300',
  ok: 'border-emerald-500/50 bg-emerald-950/60 text-emerald-300',
  error: 'border-rose-500/50 bg-rose-950/60 text-rose-300',
}

export function DetectionPanel({ status, result, offline, cameraRunning }: Props) {
  const enabled = status?.enabled === true
  const inference = status?.inferenceStatus ?? 'disabled'
  const detections = result?.detections ?? []

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">
          Object Detection
        </h2>
        <span
          className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide ${STATUS_CHIP[inference]}`}
        >
          {enabled ? `DETECTOR ${inference.toUpperCase()}` : 'DETECTION OFF'}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-md bg-slate-800/60 px-2 py-1.5">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Detector</p>
          <p className="font-mono text-sm font-semibold text-slate-200">
            {status?.detector ?? '—'}
          </p>
        </div>
        <div className="rounded-md bg-slate-800/60 px-2 py-1.5">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Model</p>
          <p
            className={`font-mono text-sm font-semibold ${
              status?.modelLoaded ? 'text-emerald-300' : 'text-slate-400'
            }`}
          >
            {status ? (status.modelLoaded ? 'LOADED' : 'MISSING') : '—'}
          </p>
        </div>
        <div className="rounded-md bg-slate-800/60 px-2 py-1.5">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Objects</p>
          <p className="font-mono text-sm font-semibold text-slate-200">
            {enabled ? String(status?.detectionCount ?? 0) : '—'}
          </p>
        </div>
      </div>

      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>
          Last inference: <span className="font-mono text-slate-300">{ago(result?.lastInferenceMs ?? null)}</span>
        </span>
        {result?.inferenceMs != null && (
          <span>
            <span className="font-mono text-slate-300">{result.inferenceMs}ms</span> / frame
          </span>
        )}
      </div>

      {detections.length > 0 && (
        <ul className="mt-3 space-y-1">
          {detections.map((d, i) => (
            <li
              key={i}
              className="flex items-center justify-between rounded-md bg-slate-800/50 px-2.5 py-1 font-mono text-xs"
            >
              <span className="font-semibold tracking-wide text-slate-200">
                {d.class_name.replace(/_/g, ' ').toUpperCase()}
              </span>
              <span className="text-slate-400">{Math.round(d.confidence * 100)}%</span>
            </li>
          ))}
        </ul>
      )}

      {enabled && detections.length === 0 && !cameraRunning && (
        <p className="mt-2 text-xs text-amber-300">Waiting for the camera to stream frames…</p>
      )}
      {offline && (
        <p className="mt-2 text-xs text-amber-300">Backend unreachable — detection unavailable.</p>
      )}
      {status?.error && <p className="mt-2 text-xs text-rose-300">{status.error}</p>}
      {!enabled && !status?.error && (
        <p className="mt-2 text-xs text-slate-500">
          Detection is disabled. Restart the backend with <code className="text-slate-400">DETECTION_ENABLED=true</code>{' '}
          (<code className="text-slate-400">DETECTION_BACKEND=mock|yolo</code>).
        </p>
      )}
    </section>
  )
}
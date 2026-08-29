import type { EventSeverity, ExperimentState } from '../domain/types'

const SEVERITY_STYLE: Record<EventSeverity, string> = {
  ok: 'border-emerald-700/50 bg-emerald-950/40 text-emerald-200',
  error: 'border-rose-700/50 bg-rose-950/40 text-rose-200',
  warn: 'border-amber-700/50 bg-amber-950/40 text-amber-200',
  info: 'border-slate-700/50 bg-slate-900/60 text-slate-200',
}

const SEVERITY_LABEL: Record<EventSeverity, string> = {
  ok: 'OK',
  error: 'ERROR',
  warn: 'WARN',
  info: 'INFO',
}

export function StatusPanel({ state }: { state: ExperimentState }) {
  const detected = state.currentDetected
  const confidence = detected ? Math.round(detected.confidence * 100) : 0
  const last = state.lastClassification
  const exp = state.experiment
  const expected = exp.steps[state.currentStepIndex]

  const counters: Array<{ label: string; value: number; accent: string }> = [
    { label: 'Out of sequence', value: state.errors.outOfSequence, accent: 'text-rose-400' },
    { label: 'Skipped', value: state.errors.skipped, accent: 'text-amber-400' },
    { label: 'Repeated', value: state.errors.repeated, accent: 'text-rose-300' },
    { label: 'Unknown', value: state.errors.unknown, accent: 'text-amber-300' },
    { label: 'Low confidence', value: state.errors.lowConfidence, accent: 'text-slate-300' },
  ]

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
        Recognition
      </h2>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-slate-500">Detected activity</p>
          <p className="mt-0.5 truncate font-mono text-lg font-semibold text-slate-100">
            {detected?.activity ?? '—'}
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wider text-slate-500">Confidence</p>
          <div className="mt-1 flex items-center gap-2">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800">
              <div
                className={`h-full rounded-full transition-all ${
                  confidence >= 80 ? 'bg-emerald-500' : confidence >= 50 ? 'bg-amber-500' : 'bg-rose-500'
                }`}
                style={{ width: `${confidence}%` }}
              />
            </div>
            <span className="font-mono text-sm text-slate-300">{confidence}%</span>
          </div>
        </div>
      </div>

      <div className="mt-3">
        <p className="text-[11px] uppercase tracking-wider text-slate-500">Next expected step</p>
        <p className="mt-0.5 text-sm font-medium text-emerald-300">
          {expected ? `${expected.activity} — ${expected.label}` : '—'}
        </p>
      </div>

      <div className="mt-3">
        <p className="text-[11px] uppercase tracking-wider text-slate-500">Detection errors</p>
        <div className="mt-1.5 grid grid-cols-1 gap-1">
          {counters.map(c => (
            <div key={c.label} className="flex items-center justify-between text-sm">
              <span className="text-slate-500">{c.label}</span>
              <span className={`font-mono font-semibold tabular-nums ${c.accent}`}>{c.value}</span>
            </div>
          ))}
        </div>
      </div>

      {last && (
        <div className={`mt-3 rounded-md border p-2.5 ${SEVERITY_STYLE[last.severity]}`}>
          <div className="flex items-center gap-2">
            <span className="rounded bg-black/30 px-1.5 py-0.5 text-[10px] font-bold tracking-wider">
              {SEVERITY_LABEL[last.severity]} · {last.kind}
            </span>
          </div>
          <p className="mt-1 text-sm">{last.message}</p>
          {last.voice && (
            <p className="mt-1 text-xs italic opacity-80">“{last.voice}”</p>
          )}
        </div>
      )}
    </section>
  )
}
import type { EngineSnapshot } from '../hooks/useExperimentEngine'

interface Props {
  snapshot: EngineSnapshot | null
  running: boolean
  onStart: () => void
  onStop: () => void
  busy: boolean
}

const STATUS_STYLE: Record<string, string> = {
  NOT_STARTED: 'border-outline-variant/50 text-on-surface-variant',
  RUNNING: 'border-primary/70 bg-primary/10 text-primary',
  WAITING_FOR_STEP: 'border-primary/70 bg-primary/10 text-primary',
  STEP_CANDIDATE: 'border-amber/70 bg-amber/10 text-amber',
  STEP_CONFIRMED: 'border-secondary/70 bg-secondary/10 text-secondary',
  SEQUENCE_VIOLATION: 'border-error/70 bg-error/10 text-error',
  UNCERTAIN: 'border-amber/70 bg-amber/10 text-amber',
  COMPLETED: 'border-secondary/70 bg-secondary/10 text-secondary',
  PAUSED: 'border-outline text-on-surface-variant',
  ABORTED: 'border-error/70 bg-error/10 text-error',
}

export function ExperimentPanel({ snapshot, running, onStart, onStop, busy }: Props) {
  if (!snapshot) {
    return (
      <section className="panel p-4">
        <h2 className="heading-title">Experiment Engine</h2>
        <p className="mt-2 font-mono text-xs text-on-surface-variant">Loading…</p>
      </section>
    )
  }

  const progress = snapshot.total_steps > 0
    ? Math.round((snapshot.completed_count / snapshot.total_steps) * 100)
    : 0

  return (
    <section className="panel p-4 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="heading-title">Experiment Engine</h2>
          <p className="mt-1 truncate font-sans text-lg font-bold text-on-surface">
            {snapshot.experiment_name}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span className={`chip border ${STATUS_STYLE[snapshot.status] ?? ''}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${running ? 'animate-pulse bg-primary' : 'bg-outline'}`} />
            {snapshot.status.replace(/_/g, ' ')}
          </span>
          {snapshot.run_id && (
            <span className="font-mono text-[9px] uppercase tracking-wider text-on-surface-variant">
              {snapshot.run_id}
            </span>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="overline-label">Progress</span>
          <span className="font-mono text-xs text-on-surface-variant">
            {snapshot.completed_count}/{snapshot.total_steps} steps
          </span>
        </div>
        <div className="h-2 w-full bg-surface-container-high">
          <div
            className="h-full bg-primary transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Current step */}
      {snapshot.current_step && (
        <div className="border border-primary/50 bg-primary/5 p-3">
          <span className="overline-label text-primary">Current Step</span>
          <p className="mt-1 font-sans text-sm font-semibold text-on-surface">
            {snapshot.current_step.label}
          </p>
          <p className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
            Step {snapshot.current_step.step_number} of {snapshot.current_step.total_steps}
            {' · '}{snapshot.current_step.activity}
          </p>
          {snapshot.current_step.description && (
            <p className="mt-1 text-xs text-on-surface-variant">{snapshot.current_step.description}</p>
          )}
        </div>
      )}

      {/* Next step */}
      {snapshot.next_step && (
        <div className="border border-outline-variant/40 bg-surface-container-low p-3">
          <span className="overline-label text-on-surface-variant">Next Step</span>
          <p className="mt-1 font-sans text-sm font-medium text-on-surface">
            {snapshot.next_step.label}
          </p>
          <p className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
            Step {snapshot.next_step.step_number} · {snapshot.next_step.activity}
          </p>
        </div>
      )}

      {/* Completed steps */}
      {snapshot.completed_steps.length > 0 && (
        <div>
          <span className="overline-label">Completed</span>
          <div className="mt-2 space-y-1">
            {snapshot.completed_steps.map(cs => (
              <div
                key={cs.step_id}
                className="flex items-center gap-2 border border-secondary/30 bg-secondary/5 px-2.5 py-1.5"
              >
                <span className="flex h-5 w-5 shrink-0 items-center justify-center bg-secondary font-mono text-[10px] font-bold text-black">
                  ✓
                </span>
                <span className="min-w-0 flex-1 truncate font-sans text-xs text-on-surface">
                  {cs.label}
                </span>
                <span className="font-mono text-[9px] text-on-surface-variant">
                  {Math.round(cs.confidence * 100)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Violations */}
      {snapshot.violations.length > 0 && (
        <div>
          <span className="overline-label text-error">Violations ({snapshot.violation_count})</span>
          <div className="mt-2 space-y-1">
            {snapshot.violations.map((v, i) => (
              <div
                key={`${v.kind}-${i}`}
                className="border border-error/30 bg-error/5 px-2.5 py-1.5"
              >
                <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-error">
                  {v.kind.replace(/_/g, ' ')}
                </p>
                <p className="mt-0.5 text-xs text-on-surface-variant">{v.message}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Last detection */}
      {snapshot.last_activity && (
        <div className="border border-outline-variant/30 bg-surface-container-low px-3 py-2">
          <span className="overline-label">Last Detected</span>
          <p className="mt-0.5 font-sans text-sm text-on-surface">
            {snapshot.last_activity.label}
            <span className="ml-2 font-mono text-xs text-on-surface-variant">
              {Math.round(snapshot.last_activity.confidence * 100)}%
            </span>
          </p>
        </div>
      )}

      {/* Controls */}
      <div className="flex items-center gap-3 border-t border-outline-variant/40 pt-4">
        <button
          type="button"
          onClick={onStart}
          disabled={running || busy || snapshot.status === 'COMPLETED'}
          className="btn-primary"
        >
          <span className="msym text-lg leading-none">rocket_launch</span>
          {running ? 'Running…' : 'Start'}
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
      </div>
    </section>
  )
}

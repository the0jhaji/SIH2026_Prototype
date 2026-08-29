import { expectedStep } from '../domain/experiment'
import type { ExperimentState } from '../domain/types'

export function StepChecklist({ state }: { state: ExperimentState }) {
  const expected = expectedStep(state.experiment, state.currentStepIndex)

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
        Procedure
      </h2>
      <ol className="space-y-1.5">
        {state.experiment.steps.map((step, i) => {
          const done = state.completedStepIds.includes(step.id)
          const current = state.status === 'RUNNING' && expected?.id === step.id
          const upNext = !done && !current

          return (
            <li
              key={step.id}
              className={`flex items-center gap-3 rounded-md border px-3 py-2 text-sm transition ${
                done
                  ? 'border-emerald-800/50 bg-emerald-950/20 text-emerald-300/90'
                  : current
                    ? 'border-emerald-500/60 bg-emerald-500/10 text-slate-100'
                    : upNext
                      ? 'border-slate-800/80 bg-slate-900/40 text-slate-500'
                      : 'border-slate-800/80 bg-slate-900/40 text-slate-400'
              }`}
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold ${
                  done
                    ? 'border-emerald-500/60 bg-emerald-500/20 text-emerald-300'
                    : current
                      ? 'border-emerald-400 bg-emerald-400 text-slate-950'
                      : 'border-slate-700 text-slate-500'
                }`}
              >
                {done ? '✓' : i + 1}
              </span>
              <div className="min-w-0">
                <p className="truncate font-medium">{step.label}</p>
                <p className="font-mono text-[10px] uppercase tracking-wider opacity-60">
                  {step.activity}
                </p>
              </div>
              {current && (
                <span className="ml-auto animate-pulse rounded bg-emerald-500 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-950">
                  Next
                </span>
              )}
            </li>
          )
        })}
      </ol>

      {state.status === 'COMPLETED' && (
        <p className="mt-3 rounded-md border border-sky-700/50 bg-sky-950/30 px-3 py-2 text-sm text-sky-200">
          All steps completed. Experiment finished.
        </p>
      )}
    </section>
  )
}
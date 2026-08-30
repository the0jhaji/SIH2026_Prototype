import { expectedStep } from '../domain/experiment'
import type { ExperimentState } from '../domain/types'

export function StepChecklist({ state }: { state: ExperimentState }) {
  const expected = expectedStep(state.experiment, state.currentStepIndex)

  return (
    <section className="panel p-4">
      <h2 className="mb-3 heading-title">
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
                  ? 'border-emerald-300/70 bg-emerald-50 text-emerald-700 dark:border-emerald-800/50 dark:bg-emerald-950/20 dark:text-emerald-300/90'
                  : current
                    ? 'border-emerald-500/60 bg-emerald-100/70 text-slate-800 dark:bg-emerald-500/10 dark:text-slate-100'
                    : upNext
                      ? 'border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800/80 dark:bg-slate-900/40'
                      : 'border-slate-200 bg-slate-50 text-slate-400 dark:border-slate-800/80 dark:bg-slate-900/40'
              }`}
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold ${
                  done
                    ? 'border-emerald-400 bg-emerald-100 text-emerald-700 dark:border-emerald-500/60 dark:bg-emerald-500/20 dark:text-emerald-300'
                    : current
                      ? 'border-emerald-500 bg-emerald-500 text-white dark:border-emerald-400 dark:bg-emerald-400 dark:text-slate-950'
                      : 'border-slate-300 text-slate-500 dark:border-slate-700'
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
                <span className="ml-auto animate-pulse rounded bg-emerald-500 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white dark:text-slate-950">
                  Next
                </span>
              )}
            </li>
          )
        })}
      </ol>

      {state.status === 'COMPLETED' && (
        <p className="mt-3 rounded-md border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-700 dark:border-sky-700/50 dark:bg-sky-950/30 dark:text-sky-200">
          All steps completed. Experiment finished.
        </p>
      )}
    </section>
  )
}
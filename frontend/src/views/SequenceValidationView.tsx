import { expectedStep } from '../domain/experiment'
import type { ExperimentState } from '../domain/types'

interface Props {
  state: ExperimentState
}

const SEVERITY_ACCENT: Record<string, string> = {
  ok: 'text-primary border-primary/50',
  error: 'text-error border-error/50',
  warn: 'text-secondary border-secondary/50',
  info: 'text-on-surface-variant border-outline-variant/50',
}

export function SequenceValidationView({ state }: Props) {
  const expected = expectedStep(state.experiment, state.currentStepIndex)
  const classifications = state.log.filter(e => e.result)
  const last = state.lastClassification

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
      <section className="panel p-4">
        <div className="flex items-center justify-between">
          <h2 className="heading-title">Timeline — Expected vs Detected</h2>
          <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
            {classifications.length} classified events
          </span>
        </div>

        <div className="mt-5 space-y-0">
          <div className="grid grid-cols-[6rem_1fr_1fr] gap-2 border-b border-outline-variant/40 pb-2 font-mono text-[9px] font-bold uppercase tracking-widest text-on-surface-variant">
            <span>Step</span>
            <span>Expected</span>
            <span>Detected / Result</span>
          </div>
          {state.experiment.steps.map((step, i) => {
            const done = state.completedStepIds.includes(step.id)
            const current = state.status === 'RUNNING' && expected?.id === step.id
            const matchedEvent = classifications.find(e => e.stepId === step.id)
            return (
              <div
                key={step.id}
                className={`grid grid-cols-[6rem_1fr_1fr] items-center gap-2 border-b border-outline-variant/20 px-2 py-2.5 ${
                  done ? 'bg-primary/5' : current ? 'bg-primary/10' : ''
                }`}
              >
                <span className="font-mono text-[11px] font-bold text-on-surface">{i + 1}</span>
                <span className="truncate font-sans text-sm text-on-surface">{step.label}</span>
                <span className="flex items-center gap-2">
                  {matchedEvent ? (
                    <ChipResult result={matchedEvent.result ?? 'UNKNOWN'} />
                  ) : done ? (
                    <span className="font-mono text-[9px] uppercase tracking-wider text-secondary">
                      completed
                    </span>
                  ) : current ? (
                    <span className="font-mono text-[9px] uppercase tracking-wider text-primary">
                      awaiting
                    </span>
                  ) : (
                    <span className="font-mono text-[9px] uppercase tracking-wider text-outline">
                      pending
                    </span>
                  )}
                </span>
              </div>
            )
          })}
        </div>
      </section>

      <div className="space-y-4">
        <section className="panel p-4">
          <h2 className="heading-title">Deviation Detail</h2>
          {last ? (
            <div className={`mt-3 border p-3 ${SEVERITY_ACCENT[last.severity] ?? SEVERITY_ACCENT.info}`}>
              <p className="font-mono text-[10px] font-bold uppercase tracking-widest">
                {last.kind.replace(/_/g, ' ')}
              </p>
              <p className="mt-1.5 font-sans text-sm text-on-surface">{last.message}</p>
              {last.activity && (
                <p className="mt-2 font-mono text-[11px] text-on-surface-variant">
                  Detected: <span className="text-primary">{last.activity.replace(/_/g, ' ')}</span>
                  {last.confidence != null && (
                    <>
                      {' '}· <span className="text-secondary">{Math.round(last.confidence * 100)}%</span>
                    </>
                  )}
                </p>
              )}
              {last.voice && (
                <p className="mt-2 font-mono text-[11px] italic text-on-surface-variant">
                  “{last.voice}”
                </p>
              )}
            </div>
          ) : (
            <p className="mt-3 font-mono text-[11px] text-on-surface-variant">
              No deviation recorded yet.
            </p>
          )}
        </section>

        <section className="panel p-4">
          <h2 className="heading-title">Astra Decision Tree</h2>
          <div className="mt-3 space-y-2 font-mono text-[11px]">
            <DecisionRow order="1" label="Expected step present" pass={state.status === 'RUNNING'} />
            <DecisionRow order="2" label="Objects above threshold" pass={state.currentDetected != null} />
            <DecisionRow order="3" label="Correct classification" pass={last?.result === 'CORRECT'} />
            <DecisionRow order="4" label="Sequence complete" pass={state.status === 'COMPLETED'} />
          </div>
        </section>
      </div>
    </div>
  )
}

function ChipResult({ result }: { result: string }) {
  const styles: Record<string, string> = {
    CORRECT: 'border-primary/60 bg-primary/10 text-primary',
    OUT_OF_SEQUENCE: 'border-error/60 bg-error/10 text-error',
    WRONG_OBJECT: 'border-error/60 bg-error/10 text-error',
    WRONG_SEQUENCE: 'border-error/60 bg-error/10 text-error',
    SKIPPED: 'border-secondary/60 bg-secondary/10 text-secondary',
    REPEATED: 'border-error/60 bg-error/10 text-error',
    UNKNOWN: 'border-outline/60 bg-surface-container-low text-on-surface-variant',
    LOW_CONFIDENCE: 'border-outline/60 bg-surface-container-low text-on-surface-variant',
  }
  return (
    <span className={`chip px-1.5 py-0.5 ${styles[result] ?? styles.UNKNOWN}`}>{result.replace(/_/g, ' ')}</span>
  )
}

function DecisionRow({ order, label, pass }: { order: string; label: string; pass: boolean }) {
  return (
    <div className="flex items-center gap-2 border border-outline-variant/30 bg-surface-container-low px-2.5 py-1.5">
      <span className="font-bold text-on-surface-variant">{order}</span>
      <span className="flex-1 text-on-surface">{label}</span>
      <span className={`msym text-lg leading-none ${pass ? 'text-primary' : 'text-outline'}`}>
        {pass ? 'check_circle' : 'cancel'}
      </span>
    </div>
  )
}

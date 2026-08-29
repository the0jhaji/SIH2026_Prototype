import { useEffect, useRef } from 'react'
import type { BasEvent, EventSeverity } from '../domain/types'
import { formatTimestamp } from '../lib/time'

const LINE_STYLE: Record<EventSeverity, string> = {
  ok: 'text-emerald-300',
  error: 'text-rose-300',
  warn: 'text-amber-300',
  info: 'text-slate-300',
}

const KIND_TAG: Record<BasEvent['kind'], string> = {
  EXPERIMENT_STARTED: 'START',
  EXPERIMENT_STOPPED: 'STOP',
  EXPERIMENT_COMPLETED: 'DONE',
  RECORDING_STARTED: 'REC·ON',
  RECORDING_STOPPED: 'REC·OFF',
  STEP_MATCHED: 'MATCH',
  OUT_OF_SEQUENCE: 'OOS',
  SKIPPED_STEP: 'SKIP',
  REPEATED_STEP: 'REPEAT',
  UNKNOWN_ACTIVITY: 'UNKNOWN',
  LOW_CONFIDENCE: 'LOWCONF',
}

export function EventLog({ events }: { events: BasEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [events.length])

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/70">
      <div className="border-b border-slate-800 px-4 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">
          Timestamped event log
        </h2>
      </div>
      <div className="h-64 overflow-y-auto px-4 py-2 font-mono text-xs">
        {events.length === 0 ? (
          <p className="py-6 text-center text-slate-600">
            No events yet. Start an experiment to begin logging.
          </p>
        ) : (
          events.map(ev => (
            <div key={ev.seq} className="flex items-baseline gap-2 border-b border-slate-800/40 py-1 last:border-0">
              <span className="shrink-0 tabular-nums text-slate-600">{formatTimestamp(ev.ts)}</span>
              <span
                className={`shrink-0 rounded bg-slate-800/80 px-1.5 py-px text-[10px] font-bold tracking-wide ${LINE_STYLE[ev.severity]}`}
              >
                {KIND_TAG[ev.kind]}
              </span>
              <span className={LINE_STYLE[ev.severity]}>{ev.message}</span>
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>
    </section>
  )
}
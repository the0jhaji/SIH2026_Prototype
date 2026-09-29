import { useEffect, useMemo, useRef, useState } from 'react'
import type { BasEvent, EventSeverity } from '../domain/types'
import { formatTimestamp } from '../lib/time'

interface Props {
  events: BasEvent[]
}

const SEVERITY_BADGE: Record<EventSeverity, string> = {
  ok: 'border-primary/60 bg-primary/10 text-primary',
  error: 'border-error/60 bg-error/10 text-error',
  warn: 'border-secondary/60 bg-secondary/10 text-secondary',
  info: 'border-outline-variant/60 bg-surface-container-high text-on-surface-variant',
}

const KIND_STRIP: Record<BasEvent['kind'], string> = {
  EXPERIMENT_STARTED: 'START',
  EXPERIMENT_STOPPED: 'STOP',
  EXPERIMENT_COMPLETED: 'DONE',
  RECORDING_STARTED: 'REC·ON',
  RECORDING_STOPPED: 'REC·OFF',
  STEP_MATCHED: 'MATCH',
  OUT_OF_SEQUENCE: 'OOS',
  WRONG_OBJECT: 'WRONGOBJ',
  WRONG_SEQUENCE: 'WRONGSEQ',
  SKIPPED_STEP: 'SKIP',
  REPEATED_STEP: 'REPEAT',
  UNKNOWN_ACTIVITY: 'UNKNOWN',
  LOW_CONFIDENCE: 'LOWCONF',
}

type Filter = EventSeverity | 'all'

export function LogsView({ events }: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const [autoscroll, setAutoscroll] = useState(true)
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoscroll) bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight })
  }, [events.length, filter, autoscroll])

  const filtered = useMemo(
    () => (filter === 'all' ? events : events.filter(e => e.severity === filter)),
    [events, filter],
  )

  const exportCsv = () => {
    const rows = [
      ['seq', 'timestamp', 'kind', 'severity', 'result', 'activity', 'confidence', 'message'],
      ...filtered.map(e => [
        String(e.seq),
        new Date(e.ts).toISOString(),
        e.kind,
        e.severity,
        e.result ?? '',
        e.activity ?? '',
        e.confidence != null ? String(e.confidence) : '',
        e.message,
      ]),
    ]
    const csv = rows.map(r => r.map(v => `"${v.replaceAll('"', '""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'astra-experiment-log.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="panel">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-outline-variant/40 px-4 py-2">
        <h2 className="heading-title">Timestamped Event Log</h2>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {(['all', 'ok', 'error', 'warn', 'info'] as Filter[]).map(f => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`border px-2 py-1 font-mono text-[9px] font-bold uppercase tracking-wider ${
                  filter === f
                    ? 'border-primary/70 bg-primary/10 text-primary'
                    : 'border-outline-variant/40 text-on-surface-variant hover:bg-surface-container-high'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          <button type="button" onClick={exportCsv} className="btn-ghost px-2 py-1">
            <span className="msym text-lg leading-none">download</span>
            Export
          </button>
          <label className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-wider text-on-surface-variant">
            <input
              type="checkbox"
              checked={autoscroll}
              onChange={e => setAutoscroll(e.target.checked)}
            />
            Tail
          </label>
        </div>
      </div>

      <div className="grid grid-cols-[4rem_7rem_6rem_1fr] gap-2 border-b border-outline-variant/40 bg-surface-container-low px-4 py-2 font-mono text-[9px] font-bold uppercase tracking-widest text-on-surface-variant">
        <span>Seq</span>
        <span>Time</span>
        <span>Kind</span>
        <span>Message</span>
      </div>

      <div ref={bodyRef} className="h-[28rem] overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="py-8 text-center font-mono text-[11px] text-on-surface-variant">
            {events.length === 0 ? 'No events yet. Start an experiment to begin logging.' : 'No events match this filter.'}
          </p>
        ) : (
          filtered.map(ev => (
            <div
              key={ev.seq}
              className="grid grid-cols-[4rem_7rem_6rem_1fr] items-center gap-2 border-b border-outline-variant/20 px-4 py-1.5 font-mono text-xs hover:bg-surface-container-low"
            >
              <span className="tabular-nums text-on-surface-variant">{ev.seq}</span>
              <span className="tabular-nums text-on-surface-variant">{formatTimestamp(ev.ts)}</span>
              <span>
                <Badge severity={ev.severity} label={KIND_STRIP[ev.kind]} />
              </span>
              <span className="text-on-surface">{ev.message}</span>
            </div>
          ))
        )}
      </div>
    </section>
  )
}

function Badge({ severity, label }: { severity: EventSeverity; label: string }) {
  return (
    <span className={`chip px-1.5 py-0.5 text-[9px] ${SEVERITY_BADGE[severity]}`}>{label}</span>
  )
}

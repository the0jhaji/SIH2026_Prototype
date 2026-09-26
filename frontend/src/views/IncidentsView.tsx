import { useMemo, useState } from 'react'
import { ALERT_COLORS, riskPercent, type Incident, type SafetyEvent } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import { Badge, EmptyState, KeyValue, MetricCard, Panel, SubCard } from './ui'
import { DataTable, FilterBar, PageShell, Timeline } from './layout'
import { relativeAge, safetyEventEntries, severityColor } from './helpers'
import type { SafetyCommonProps } from './props'

type Scope = 'INCIDENTS' | 'EVENTS'

const STATE_TONE: Record<Incident['state'], string> = {
  OPEN: ALERT_COLORS.EMERGENCY,
  ACKNOWLEDGED: '#a78bfa',
  RESOLVED: '#22c55e',
}

/**
 * Logs (view 8).
 *
 * Two real record sets — the incident register and the safety event stream —
 * with a search box, filters and a detail pane. Rows are selectable because a
 * log without its record contents is only half a log; nothing is aggregated
 * away and no severity is recomputed here.
 */
export function IncidentsView({ safety }: SafetyCommonProps) {
  const [scope, setScope] = useState<Scope>('INCIDENTS')
  const [query, setQuery] = useState('')
  const [stateFilter, setStateFilter] = useState('ALL')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const incidents = safety.incidents
  const events = safety.events
  const open = incidents.filter(i => i.state === 'OPEN')
  const resolved = incidents.filter(i => i.state === 'RESOLVED')
  const escalated = incidents.filter(i => i.escalation != null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return incidents
      .filter(i => stateFilter === 'ALL' || i.state === stateFilter)
      .filter(i =>
        !q
          ? true
          : [i.incident_id, i.event_type, i.severity, i.description, i.trigger_key, i.source]
              .join(' ')
              .toLowerCase()
              .includes(q),
      )
  }, [incidents, stateFilter, query])

  const selected = filtered.find(i => i.incident_id === selectedId) ?? filtered[0] ?? null
  const timeline = useMemo(() => safetyEventEntries(events, 60), [events])
  const filteredEvents = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return events
    return events.filter(e => `${e.kind} ${e.message} ${e.severity}`.toLowerCase().includes(q))
  }, [events, query])

  return (
    <PageShell>
      {/* ── Log summary ──────────────────────────────────────────── */}
      <div className="grid shrink-0 grid-cols-2 gap-[var(--grid-gap)] lg:grid-cols-4">
        <MetricCard
          label="Incidents"
          value={String(incidents.length)}
          sub={`${open.length} open · ${resolved.length} resolved`}
          color={incidents.length ? '#f97316' : '#64748b'}
          active={incidents.length > 0}
        />
        <MetricCard
          label="Events"
          value={String(events.length)}
          sub="safety engine stream"
          color={events.length ? '#38bdf8' : '#64748b'}
          active={events.length > 0}
        />
        <MetricCard
          label="Escalations"
          value={String(escalated.length)}
          sub="staged packages"
          color={escalated.length ? '#facc15' : '#64748b'}
          active={escalated.length > 0}
        />
        <MetricCard
          label="Newest record"
          value={relativeAge(newestRecordTs(incidents, events))}
          sub="age of the most recent entry"
          color="#64748b"
        />
      </div>

      {/* ── Records + detail ─────────────────────────────────────── */}
      <div className="page-fill grid-cols-1 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Panel
          title={scope === 'INCIDENTS' ? 'Incident Register' : 'Safety Event Stream'}
          fill
          scroll
          right={
            <FilterBar
              options={[
                { value: 'INCIDENTS', label: 'Incidents', count: incidents.length },
                { value: 'EVENTS', label: 'Events', count: events.length },
              ]}
              value={scope}
              onChange={v => setScope(v as Scope)}
            />
          }
        >
          {scope === 'INCIDENTS' ? (
            <>
              <div className="mb-2 flex flex-wrap items-center gap-1.5">
                {(['ALL', 'OPEN', 'ACKNOWLEDGED', 'RESOLVED'] as const).map(s => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStateFilter(s)}
                    aria-pressed={stateFilter === s}
                    className={`border px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-wider ${
                      stateFilter === s
                        ? 'border-primary bg-primary/15 text-primary'
                        : 'border-outline-variant/50 bg-surface-container-low text-on-surface-variant'
                    }`}
                  >
                    {s}
                    <span className="ml-1 opacity-70">
                      {s === 'ALL' ? incidents.length : incidents.filter(i => i.state === s).length}
                    </span>
                  </button>
                ))}
                <SearchBox value={query} onChange={setQuery} placeholder="Search id, event, trigger…" />
              </div>
              <DataTable
                rows={filtered}
                rowKey={i => i.incident_id}
                selectedKey={selected?.incident_id}
                onSelect={i => setSelectedId(i.incident_id)}
                empty={
                  <EmptyState
                    icon="table_rows"
                    title="No matching incidents"
                    description={
                      incidents.length === 0
                        ? 'Incidents are opened when a confirmed CRITICAL or EMERGENCY event is detected. Nothing has been recorded yet.'
                        : 'No incident matches the current filter and search.'
                    }
                    status={safety.offline ? 'Backend offline — polling.' : undefined}
                  />
                }
                columns={[
                  {
                    header: 'Severity',
                    render: i => (
                      <span className="font-bold uppercase" style={{ color: severityColor(i.severity) }}>
                        {i.severity}
                      </span>
                    ),
                  },
                  { header: 'Event', render: i => <span className="uppercase">{i.event_type}</span> },
                  { header: 'State', render: i => <span style={{ color: STATE_TONE[i.state] }}>{i.state}</span> },
                  { header: 'Conf', render: i => riskPercent(i.confidence) },
                  { header: 'Age', render: i => relativeAge(i.timestamp) },
                  { header: 'Recorded', render: i => formatTimestamp(i.timestamp) },
                ]}
              />
            </>
          ) : (
            <>
              <div className="mb-2">
                <SearchBox value={query} onChange={setQuery} placeholder="Search kind, message, severity…" />
              </div>
              <DataTable
                rows={filteredEvents}
                rowKey={e => `event-${e.seq}`}
                empty={
                  <EmptyState
                    icon="stream"
                    title="No matching events"
                    description={
                      events.length === 0
                        ? 'The safety engine publishes a transition each time the monitor, alert or incident state changes.'
                        : 'No event matches the current search.'
                    }
                    status={safety.offline ? 'Backend offline — polling.' : undefined}
                  />
                }
                columns={[
                  { header: 'Seq', render: e => `#${e.seq}` },
                  { header: 'Kind', render: e => <span className="uppercase">{String(e.kind)}</span> },
                  {
                    header: 'Severity',
                    render: e => (
                      <span className="uppercase" style={{ color: severityColor(e.severity) }}>
                        {e.severity}
                      </span>
                    ),
                  },
                  { header: 'Message', render: e => e.message },
                  { header: 'Age', render: e => relativeAge(e.ts) },
                ]}
              />
            </>
          )}
        </Panel>

        <div className="grid min-h-0 grid-rows-[minmax(0,1.2fr)_minmax(0,1fr)] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="Record Detail"
            fill
            scroll
            right={
              selected ? (
                <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                  {selected.incident_id}
                </span>
              ) : null
            }
          >
            {selected ? (
              <div className="stack">
                <div className="flex items-start justify-between gap-2">
                  <p
                    className="min-w-0 truncate font-mono text-[11px] font-bold uppercase tracking-wider"
                    style={{ color: severityColor(selected.severity) }}
                  >
                    {selected.severity} — {selected.event_type.replace(/_/g, ' ')}
                  </p>
                  <Badge color={STATE_TONE[selected.state]} pulse={selected.state === 'OPEN'}>
                    {selected.state}
                  </Badge>
                </div>
                <p className="font-mono text-[11px] leading-snug text-on-surface">
                  {selected.description}
                </p>
                {selected.recommended_action && (
                  <p
                    className="font-mono text-[11px] font-semibold"
                    style={{ color: severityColor(selected.severity) }}
                  >
                    Action: {selected.recommended_action}
                  </p>
                )}
                <SubCard title="Provenance">
                  <KeyValue label="Incident id" value={selected.incident_id} />
                  <KeyValue label="Trigger key" value={selected.trigger_key} />
                  <KeyValue label="Source" value={selected.source} />
                  <KeyValue label="Mission state" value={selected.mission_state} />
                  <KeyValue label="Confidence" value={riskPercent(selected.confidence)} />
                  <KeyValue label="Recorded" value={formatTimestamp(selected.timestamp)} />
                  <KeyValue label="Age" value={relativeAge(selected.timestamp)} />
                </SubCard>
                {selected.assessment && (
                  <SubCard title="Triggering assessment">
                    <KeyValue
                      label="Object"
                      value={selected.assessment.object.replace(/_/g, ' ')}
                    />
                    <KeyValue label="Risk" value={selected.assessment.risk_level} color={severityColor(selected.assessment.risk_level)} />
                    <KeyValue
                      label="Score"
                      value={riskPercent(selected.assessment.risk_score)}
                    />
                    <KeyValue
                      label="Confirmed"
                      value={selected.assessment.confirmed ? 'yes' : 'no'}
                    />
                    <KeyValue
                      label="Near crew"
                      value={selected.assessment.near_astronaut ? 'yes' : 'no'}
                    />
                    <p className="mt-1 font-mono text-[10px] leading-snug text-on-surface-variant">
                      {selected.assessment.reason}
                    </p>
                  </SubCard>
                )}
                <SubCard title={`Evidence (${selected.evidence.length})`}>
                  {selected.evidence.length === 0 ? (
                    <p className="font-mono text-[10px] text-on-surface-variant">
                      No evidence frame was captured for this incident.
                    </p>
                  ) : (
                    <ul className="rows">
                      {selected.evidence.map(e => (
                        <li key={`${e.type}-${e.captured_at}`} className="truncate font-mono text-[10px]">
                          <span className="font-semibold uppercase tracking-wider">{e.type}</span>{' '}
                          <span className="text-on-surface-variant">
                            {formatTimestamp(e.captured_at)} · {e.path}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </SubCard>
                {selected.escalation && (
                  <SubCard title="Escalation">
                    <KeyValue label="Status" value={selected.escalation.status} color="#facc15" />
                    <KeyValue label="Criteria" value={selected.escalation.criteria} />
                    <p className="break-all font-mono text-[10px] text-on-surface-variant">
                      {selected.escalation.path}
                    </p>
                  </SubCard>
                )}
              </div>
            ) : (
              <EmptyState
                icon="article"
                title="No record selected"
                description={
                  incidents.length === 0
                    ? 'The incident register is empty. Select a record once an incident exists.'
                    : 'Select a row from the register to inspect its evidence and provenance.'
                }
              />
            )}
          </Panel>

          <Panel
            title="Recent Timeline"
            fill
            scroll
            right={
              <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                {timeline.length} events
              </span>
            }
          >
            <Timeline
              entries={timeline}
              empty={
                <EmptyState
                  compact
                  icon="history"
                  title="No events recorded"
                  description="Monitor, alert and incident transitions are appended here as they happen."
                />
              }
            />
          </Panel>
        </div>
      </div>
    </PageShell>
  )
}

function SearchBox({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  return (
    <label className="ml-auto flex min-w-[12rem] flex-1 items-center gap-1.5 border border-outline-variant/50 bg-surface-container-low px-2 py-1 sm:flex-none">
      <span className="msym text-sm leading-none text-on-surface-variant" aria-hidden="true">
        search
      </span>
      <input
        type="search"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-on-surface placeholder:text-on-surface-variant/60 focus:outline-none"
      />
    </label>
  )
}

function newestRecordTs(incidents: Incident[], events: SafetyEvent[]): number | null {
  const stamps = [
    ...incidents.map(i => i.timestamp),
    ...events.map(e => e.ts),
  ].filter(v => typeof v === 'number' && Number.isFinite(v))
  return stamps.length ? Math.max(...stamps) : null
}

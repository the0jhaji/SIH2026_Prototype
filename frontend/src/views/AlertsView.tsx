import { useMemo, useState, type ReactNode } from 'react'
import { ALERT_COLORS, riskPercent, tint, type SafetyAlert } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import { Badge, EmptyState, MetricCard, Panel, StatTile, SubCard } from './ui'
import { PageShell } from './layout'
import { severityColor, stateColor } from './helpers'
import type { SafetyCommonProps } from './props'

type Filter = 'ALL' | 'EMERGENCY' | 'CRITICAL' | 'WARNING' | 'CAUTION' | 'RESOLVED'

/**
 * Alert board.
 *
 * A lifecycle summary, the live queue beside an intelligence column that
 * explains *why* an alert exists, and a filterable resolved history. The
 * filters are a view over already-loaded alerts — they do not decide what
 * is an alert.
 */
export function AlertsView({ safety }: SafetyCommonProps) {
  const [filter, setFilter] = useState<Filter>('ALL')
  const all = safety.alerts
  const active = useMemo(() => all.filter(a => !a.resolved), [all])
  const resolved = useMemo(() => all.filter(a => a.resolved), [all])
  const acknowledged = active.filter(a => a.acknowledged)
  const escalated = active.filter(a => a.incident_id != null)

  const visible = useMemo(() => {
    const pool = filter === 'RESOLVED' ? resolved : active
    if (filter === 'ALL' || filter === 'RESOLVED') return pool
    return pool.filter(a => a.level === filter)
  }, [filter, active, resolved])

  const countFor = (f: Filter) => {
    if (f === 'ALL') return active.length
    if (f === 'RESOLVED') return resolved.length
    return active.filter(a => a.level === f).length
  }

  return (
    <PageShell>
      {/* ── Lifecycle summary ────────────────────────────────────── */}
      <div className="grid shrink-0 grid-cols-2 gap-[var(--grid-gap)] lg:grid-cols-4">
        <MetricCard
          label="Active"
          value={String(active.length)}
          sub={`${active.filter(a => !a.acknowledged).length} unacknowledged`}
          color={active.length ? '#ef4444' : '#22c55e'}
          active={active.length > 0}
        />
        <MetricCard
          label="Acknowledged"
          value={String(acknowledged.length)}
          sub="operator responsible"
          color={acknowledged.length ? '#a78bfa' : '#64748b'}
          active={acknowledged.length > 0}
        />
        <MetricCard
          label="Escalated"
          value={String(escalated.length)}
          sub={`${safety.status?.escalations_ready ?? 0} packages ready`}
          color={escalated.length ? '#f97316' : '#64748b'}
          active={escalated.length > 0}
        />
        <MetricCard
          label="Resolved"
          value={String(resolved.length)}
          sub={`${all.length} lifetime`}
          color="#22c55e"
        />
      </div>

      {/* ── Active queue + intelligence ──────────────────────────── */}
      <div className="page-fill grid-cols-1 lg:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
        <Panel
          title="Active Alerts"
          fill
          scroll
          right={
            <div className="scroll-x flex items-center gap-1">
              {(['ALL', 'EMERGENCY', 'CRITICAL', 'WARNING', 'CAUTION'] as const).map(f => (
                <FilterChip key={f} active={filter === f} onClick={() => setFilter(f)}>
                  {f} <span className="ml-1 opacity-70">{countFor(f)}</span>
                </FilterChip>
              ))}
            </div>
          }
        >
          {visible.length === 0 ? (
            <EmptyState
              icon="notifications_off"
              title="No active alerts"
              description={
                safety.offline
                  ? 'Backend offline — polling.'
                  : 'ASTRA has not generated an active alert. Alerts de-duplicate by root cause and escalate in place rather than repeating.'
              }
              lastUpdated={
                safety.snapshot?.timestamp
                  ? `Last assessment ${formatTimestamp(safety.snapshot.timestamp)}`
                  : undefined
              }
            />
          ) : (
            <ul className="rows">
              {visible.map(a => (
                <AlertCard key={a.id} alert={a} onAck={() => safety.ack(a.id)} />
              ))}
            </ul>
          )}
        </Panel>

        <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="Alert Intelligence"
            right={
              <Badge color={safety.status ? MISSION_TONE : '#64748b'}>
                {safety.snapshot?.mission_state ?? '—'}
              </Badge>
            }
          >
            <div className="grid grid-cols-3 gap-[var(--row-pad)]">
              <StatTile
                label="Active"
                value={String(safety.status?.alerts_active ?? 0)}
                color={(safety.status?.alerts_active ?? 0) > 0 ? '#ef4444' : undefined}
              />
              <StatTile
                label="Open incidents"
                value={String(safety.status?.incidents_open ?? 0)}
              />
              <StatTile
                label="Emergency incidents"
                value={String(safety.status?.emergency_incidents ?? 0)}
                color={(safety.status?.emergency_incidents ?? 0) > 0 ? '#ef4444' : undefined}
              />
            </div>
            <div className="mt-2 grid grid-cols-1 gap-[var(--row-pad)] sm:grid-cols-2">
              <SubCard title="Escalation rules">
                <p className="font-mono text-[10px] leading-snug text-on-surface-variant">
                  An alert is de-duplicated by its root-cause key, so one hazard never produces a
                  stream of duplicates. Level changes escalate in place and the alert cools down
                  before it can fire again.
                </p>
              </SubCard>
              <SubCard title="Acknowledgement">
                <p className="font-mono text-[10px] leading-snug text-on-surface-variant">
                  Acknowledging transfers responsibility to the operator: the alert stays visible
                  and keeps its severity until the backend resolves it. It cannot be cleared from
                  this screen.
                </p>
              </SubCard>
            </div>
          </Panel>

          <Panel
            title="Recommended Actions"
            fill
            scroll
            right={
              <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                {active.length} active
              </span>
            }
          >
            {active.length === 0 ? (
              <EmptyState
                compact
                icon="check_circle"
                title="Nothing to act on"
                description="Recommended actions are derived from the hazard knowledge base and appear with the alert that raised them."
              />
            ) : (
              <ul className="rows">
                {active.map(a => (
                  <li
                    key={`action-${a.id}`}
                    className="border px-2 py-1.5"
                    style={{ borderLeftWidth: 3, borderLeftColor: ALERT_COLORS[a.level] }}
                  >
                    <p className="truncate font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                      {a.object ?? a.event_type.replace(/_/g, ' ')} · {a.level}
                    </p>
                    <p className="font-mono text-[11px]" style={{ color: ALERT_COLORS[a.level] }}>
                      {a.recommended_action || 'No action recorded.'}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>

      {/* ── Resolved history ─────────────────────────────────────── */}
      <div
        className="page-fill shrink-0 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_18rem]"
        style={{ height: 'var(--strip-h)', flex: 'none' }}
      >
        <Panel
          title="Resolved Alert History"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {resolved.length} resolved
            </span>
          }
        >
          {resolved.length === 0 ? (
            <EmptyState
              compact
              icon="history_toggle_off"
              title="Nothing resolved yet"
              description="Alerts move here once the backend confirms the condition that raised them has cleared."
            />
          ) : (
            <ul className="rows">
              {resolved.map(a => (
                <AlertCard key={a.id} alert={a} onAck={() => undefined} />
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Alert Sources" fill scroll>
          <div className="stack">
            <SubCard title="Safety engine">
              <p className="font-mono text-[10px] text-on-surface-variant">
                Monitor {safety.snapshot?.monitor.state ?? '—'} ·{' '}
                {stateColor(safety.snapshot?.mission_state) === '#22c55e' ? 'normal' : 'elevated'}
              </p>
            </SubCard>
            <SubCard title="Detector">
              <p className="font-mono text-[10px] text-on-surface-variant">
                {safety.snapshot?.detector ?? '—'} · {safety.snapshot?.environment_mode ?? '—'}
              </p>
            </SubCard>
            <SubCard title="Attendance">
              <p className="font-mono text-[10px] text-on-surface-variant">
                {safety.status ? 'Attendance chain contributes unattended alerts.' : 'Status unavailable.'}
              </p>
            </SubCard>
          </div>
        </Panel>
      </div>
    </PageShell>
  )
}

const MISSION_TONE = stateColor('NORMAL')

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`shrink-0 whitespace-nowrap border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider transition ${
        active
          ? 'border-primary bg-primary/15 text-primary'
          : 'border-outline-variant/50 bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'
      }`}
    >
      {children}
    </button>
  )
}

function AlertCard({ alert, onAck }: { alert: SafetyAlert; onAck: () => void }) {
  const color = ALERT_COLORS[alert.level] ?? ALERT_COLORS.INFO
  return (
    <li
      className="border bg-surface-container-low p-2"
      style={{ borderColor: tint(color, 0.35), borderLeftWidth: 3, borderLeftColor: color }}
    >
      <div className="flex items-start justify-between gap-2">
        <p
          className="min-w-0 truncate font-mono text-[11px] font-bold uppercase tracking-wider"
          style={{ color }}
        >
          {alert.level} — {alert.title}
        </p>
        <Badge color={severityColor(alert.level)}>{alert.event_type.replace(/_/g, ' ')}</Badge>
      </div>
      <p className="mt-0.5 font-mono text-[11px] text-on-surface">{alert.message}</p>
      <p className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
        {alert.object ?? '—'} · conf {riskPercent(alert.confidence)} · raised{' '}
        {formatTimestamp(alert.created_at)}
        {alert.acknowledged ? ` · acked ${formatTimestamp(alert.acked_at ?? alert.updated_at)}` : ''}
        {alert.resolved ? ` · resolved ${formatTimestamp(alert.resolved_at ?? alert.updated_at)}` : ''}
        {alert.incident_id ? ` · incident ${alert.incident_id}` : ''}
      </p>
      {alert.recommended_action && (
        <p className="mt-0.5 font-mono text-[11px] font-semibold" style={{ color }}>
          Action: {alert.recommended_action}
        </p>
      )}
      {alert.ack_note && (
        <p className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
          Note: {alert.ack_note}
        </p>
      )}
      {!alert.resolved && !alert.acknowledged && (
        <button type="button" onClick={onAck} className="btn-outline mt-1.5 px-2 py-1 text-[10px]">
          Acknowledge
        </button>
      )}
      {!alert.resolved && alert.acknowledged && (
        <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
          Acknowledged — operator responsible.
        </p>
      )}
    </li>
  )
}

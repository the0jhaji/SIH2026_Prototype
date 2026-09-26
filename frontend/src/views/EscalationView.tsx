import { useMemo } from 'react'
import { riskPercent, tint, type Incident } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import { Badge, EmptyState, KeyValue, MetricCard, Panel, StatTile, SubCard } from './ui'
import { PageShell, Timeline } from './layout'
import { safetyEventEntries, severityColor } from './helpers'
import type { SafetyCommonProps } from './props'

/**
 * Earth escalation (view 7).
 *
 * The prototype has no comms link, so this screen is deliberately a
 * *staging* console: it shows what would be packaged, under which criteria,
 * and the exact local path — and says plainly that nothing has been sent.
 * A "transmitted" claim would be a lie, so there is no such state here.
 */
export function EscalationView({ safety }: SafetyCommonProps) {
  const incidents = safety.incidents
  const staged = useMemo(() => incidents.filter(i => i.escalation != null), [incidents])
  const ready = useMemo(
    () => staged.filter(i => i.escalation?.status === 'READY'),
    [staged],
  )
  const pending = useMemo(
    () => staged.filter(i => i.escalation?.status !== 'READY'),
    [staged],
  )
  const emergencyIncidents = incidents.filter(
    i => i.event_type.includes('EMERGENCY') || i.severity === 'EMERGENCY',
  )
  const evidenceTotal = incidents.reduce((n, i) => n + i.evidence.length, 0)
  const timeline = useMemo(() => safetyEventEntries(safety.events, 40), [safety.events])

  return (
    <PageShell>
      {/* ── Escalation summary ───────────────────────────────────── */}
      <div className="grid shrink-0 grid-cols-2 gap-[var(--grid-gap)] lg:grid-cols-4">
        <MetricCard
          label="Packages ready"
          value={String(ready.length)}
          sub="staged on-board, not sent"
          color={ready.length ? '#facc15' : '#64748b'}
          active={ready.length > 0}
        />
        <MetricCard
          label="Pending criteria"
          value={String(pending.length)}
          sub="below escalation threshold"
          color={pending.length ? '#f97316' : '#64748b'}
          active={pending.length > 0}
        />
        <MetricCard
          label="Emergency incidents"
          value={String(emergencyIncidents.length)}
          sub="auto-escalate candidates"
          color={emergencyIncidents.length ? '#ef4444' : '#64748b'}
          active={emergencyIncidents.length > 0}
        />
        <MetricCard
          label="Evidence frames"
          value={String(evidenceTotal)}
          sub="captured locally"
          color={evidenceTotal ? '#38bdf8' : '#64748b'}
          active={evidenceTotal > 0}
        />
      </div>

      {/* ── 60/40: packages + contract ────────────────────────────── */}
      <div className="page-fill grid-cols-1 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="Earth Escalation Packages"
            fill
            scroll
            right={
              <Badge color={ready.length ? '#facc15' : '#64748b'}>
                {ready.length} ready · {pending.length} pending
              </Badge>
            }
          >
            {staged.length === 0 ? (
              <EmptyState
                icon="outgoing_mail"
                title="No escalation packages"
                description={
                  safety.offline
                    ? 'Backend offline — polling for incidents and escalation criteria.'
                    : 'A package is staged when an incident satisfies the escalation criteria in the hazard knowledge base. Nothing has met them yet.'
                }
                status={`${safety.status?.escalations_ready ?? 0} reported ready by the backend`}
                lastUpdated={
                  safety.snapshot?.timestamp
                    ? `last assessment ${formatTimestamp(safety.snapshot.timestamp)}`
                    : undefined
                }
              />
            ) : (
              <ul className="rows">
                {staged.map(i => (
                  <EscalationCard key={i.incident_id} incident={i} />
                ))}
              </ul>
            )}
          </Panel>

          <Panel
            title="Criteria & Staging Contract"
            className="shrink-0"
            accent={ready.length ? '#facc15' : undefined}
          >
            <div className="grid grid-cols-1 gap-[var(--row-pad)] sm:grid-cols-3">
              <SubCard title="What triggers staging">
                <ul className="font-mono text-[10px] leading-relaxed text-on-surface-variant">
                  <li>· Confirmed CRITICAL hazard near the crew</li>
                  <li>· Confirmed emergency (absence · stillness · collision)</li>
                  <li>· CRITICAL severity sustained beyond the persist threshold</li>
                </ul>
              </SubCard>
              <SubCard title="What is written">
                <p className="font-mono text-[10px] leading-relaxed text-on-surface-variant">
                  Each package is serialised to{' '}
                  <code className="text-secondary">data/incidents/&lt;id&gt;/escalation.json</code> with
                  the status <span className="text-secondary">EARTH_ESCALATION_PACKAGE_READY</span>, the
                  evidence manifest and the recommended action.
                </p>
              </SubCard>
              <SubCard title="What is NOT claimed">
                <p className="font-mono text-[10px] leading-relaxed text-on-surface-variant">
                  No spacecraft link exists in this prototype. Nothing is transmitted, acknowledged or
                  received; staging is a manual hand-off and the package remains on-board.
                </p>
              </SubCard>
            </div>
          </Panel>
        </div>

        <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="Transmission Contract"
            right={
              <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
                prototype · local only
              </span>
            }
          >
            <div className="grid grid-cols-2 gap-[var(--row-pad)]">
              <StatTile
                label="Link state"
                value="NO LINK"
                color="#64748b"
                title="No ground segment is reachable from this build."
              />
              <StatTile
                label="Transmitted"
                value="0"
                color="#64748b"
                title="Intentionally always zero — see the contract below."
              />
            </div>
            <div className="mt-2">
              <KeyValue label="Transport" value="local filesystem (on-board)" />
              <KeyValue label="Protocol" value="none — manual hand-off" />
              <KeyValue label="Acknowledgement" value="not applicable" />
              <KeyValue
                label="Backend flag"
                value={safety.status ? 'EARTH_ESCALATION_ENABLED' : 'status unavailable'}
                color={safety.status ? '#22c55e' : '#64748b'}
              />
            </div>
            <p className="mt-2 font-mono text-[10px] leading-relaxed text-on-surface-variant">
              A real comms layer would plug in behind the same transport interface: the package
              content and criteria are already final, so only the delivery step is missing.
            </p>
          </Panel>

          <Panel
            title="Escalation Event Log"
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
                  icon="history"
                  title="No escalation events"
                  description="Hazard escalations, package staging and incident transitions appear here in order."
                />
              }
            />
          </Panel>
        </div>
      </div>
    </PageShell>
  )
}

function EscalationCard({ incident }: { incident: Incident }) {
  const color = severityColor(incident.severity)
  const ready = incident.escalation?.status === 'READY'
  return (
    <li
      className="border bg-surface-container-low p-2"
      style={{ borderLeftWidth: 3, borderLeftColor: color, borderColor: tint(color, 0.35) }}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 truncate font-mono text-[11px] font-bold uppercase tracking-wider" style={{ color }}>
          {incident.severity} — {incident.event_type.replace(/_/g, ' ')}
        </p>
        <Badge color={ready ? '#facc15' : '#f97316'} pulse={ready}>
          {ready ? 'Package ready' : (incident.escalation?.status ?? 'PENDING')}
        </Badge>
      </div>
      <p className="mt-0.5 font-mono text-[11px] text-on-surface">{incident.description}</p>
      {incident.recommended_action && (
        <p className="mt-0.5 font-mono text-[11px] font-semibold" style={{ color }}>
          Action: {incident.recommended_action}
        </p>
      )}
      <p className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
        {incident.incident_id} · {incident.state} · conf {riskPercent(incident.confidence)} ·{' '}
        {formatTimestamp(incident.timestamp)}
      </p>
      {incident.escalation && (
        <div className="mt-1 border-t border-outline-variant/20 pt-1">
          <KeyValue label="Criteria" value={incident.escalation.criteria} />
          <KeyValue
            label="Staged"
            value={
              incident.escalation.created_at
                ? formatTimestamp(incident.escalation.created_at)
                : 'not written'
            }
          />
          <p className="break-all font-mono text-[10px] text-on-surface-variant">
            {incident.escalation.path}
          </p>
        </div>
      )}
      {incident.evidence.length > 0 && (
        <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
          evidence {incident.evidence.map(e => `${e.type}@${formatTimestamp(e.captured_at)}`).join(' · ')}
        </p>
      )}
      <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant/70">
        local staging only — not transmitted
      </p>
    </li>
  )
}

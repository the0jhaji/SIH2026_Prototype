import { ALERT_COLORS, riskPercent, type Incident } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import type { SafetyCommonProps } from './props'
import { Badge, Empty, Panel } from './ui'

export function IncidentsView({ safety }: SafetyCommonProps) {
  const incidents = safety.incidents
  return (
    <Panel
      title="Incident History"
      right={<span className="font-mono text-sm font-bold text-on-surface">{incidents.length}</span>}
    >
      {incidents.length === 0 ? (
        <Empty
          label={
            safety.offline
              ? 'Backend offline — polling.'
              : 'No incidents recorded. Incidents capture evidence (frame + metadata) when confirmed CRITICAL/EMERGENCY events occur.'
          }
        />
      ) : (
        <ul className="mt-1 space-y-2">
          {incidents.map(i => (
            <IncidentRow key={i.incident_id} incident={i} />
          ))}
        </ul>
      )}
    </Panel>
  )
}

function IncidentRow({ incident }: { incident: Incident }) {
  const color = ALERT_COLORS[incident.severity as keyof typeof ALERT_COLORS] ?? ALERT_COLORS.INFO
  const stateLabel = incident.state
  const stateColor =
    incident.state === 'OPEN'
      ? ALERT_COLORS.EMERGENCY
      : incident.state === 'ACKNOWLEDGED'
        ? '#a78bfa'
        : '#22c55e'
  return (
    <li
      className="border border-outline-variant/30 bg-surface-container-low p-3"
      style={{ borderLeftWidth: 3, borderLeftColor: color }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-mono text-xs font-bold uppercase tracking-wider" style={{ color }}>
          {incident.severity} — {incident.event_type.replace(/_/g, ' ')}
        </p>
        <Badge color={stateColor} pulse={incident.state === 'OPEN'}>
          {stateLabel}
        </Badge>
      </div>
      <p className="mt-1 font-mono text-[11px] text-on-surface">{incident.description}</p>
      <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
        {incident.incident_id} · {formatTimestamp(incident.timestamp)} · trigger{' '}
        {incident.trigger_key} · conf {riskPercent(incident.confidence)}
      </p>
      {incident.recommended_action && (
        <p className="mt-1 font-mono text-[11px]" style={{ color }}>
          ACTION: {incident.recommended_action}
        </p>
      )}
      {incident.evidence.length > 0 && (
        <p className="mt-2 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
          evidence: {incident.evidence.map(e => `${e.type}@${formatTimestamp(e.captured_at)}`).join(' · ')}
        </p>
      )}
    </li>
  )
}
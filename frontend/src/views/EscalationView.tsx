import { ALERT_COLORS, tint, type Incident } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import type { SafetyCommonProps } from './props'
import { Badge, Empty, Panel } from './ui'

export function EscalationView({ safety }: SafetyCommonProps) {
  const escalations = safety.incidents.filter(i => i.escalation?.status === 'READY')
  const enabled = safety.status ? escalations.length > 0 || safety.status.escalations_ready > 0 : false
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="Earth Escalation Packages">
        {escalations.length === 0 ? (
          <Empty
            label={
              'No escalated packages yet. Packages are staged when an incident reaches the escalation minimum severity — locally only, never transmitted.'
            }
          />
        ) : (
          <ul className="mt-1 space-y-3">
            {escalations.map(i => (
              <EscalationCard key={i.incident_id} incident={i} />
            ))}
          </ul>
        )}
        <div className="mt-3 flex items-center gap-2 border border-outline-variant/30 bg-surface-container-low px-3 py-2">
          <span className="h-2 w-2 rounded-full" style={{ background: enabled ? '#22c55e' : '#64748b' }} />
          <p className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
            {enabled ? 'staging active (location: on-board)' : 'no packages staged'}
          </p>
        </div>
      </Panel>

      <Panel title="Transmission Contract">
        <p className="mt-1 font-mono text-xs leading-relaxed text-on-surface">
          Packages are written to <code className="text-secondary">data/incidents/&lt;id&gt;/escalation.json</code>{' '}
          with status <Badge color="#facc15">EARTH_ESCALATION_PACKAGE_READY</Badge>.
        </p>
        <ul className="mt-3 space-y-1.5 font-mono text-[11px] text-on-surface-variant">
          <li>· No real spacecraft or Earth link exists in this prototype.</li>
          <li>· Staging is manual hand-off — nothing claims to have been transmitted.</li>
          <li>· A real comms layer plugs in behind the same transport interface.</li>
        </ul>
      </Panel>
    </div>
  )
}

function EscalationCard({ incident }: { incident: Incident }) {
  const color = ALERT_COLORS[incident.severity as keyof typeof ALERT_COLORS] ?? ALERT_COLORS.INFO
  return (
    <li
      className="border bg-surface-container-low p-3"
      style={{ borderLeftWidth: 3, borderLeftColor: color, borderColor: tint(color, 0.35) }}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-xs font-bold uppercase tracking-wider" style={{ color }}>
          {incident.severity} — {incident.event_type.replace(/_/g, ' ')}
        </p>
        <Badge color="#facc15" pulse>
          PACKAGE READY
        </Badge>
      </div>
      <p className="mt-1 font-mono text-[11px] text-on-surface">{incident.description}</p>
      <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
        {incident.incident_id} · {formatTimestamp(incident.timestamp)}
      </p>
      {incident.escalation && (
        <p className="mt-2 break-all font-mono text-[10px] text-on-surface-variant">
          criteria {incident.escalation.criteria} · {incident.escalation.path}
        </p>
      )}
    </li>
  )
}
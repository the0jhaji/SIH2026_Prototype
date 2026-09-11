import { ALERT_COLORS, riskPercent, tint, type SafetyAlert } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import type { SafetyCommonProps } from './props'
import { Badge, Empty, Panel } from './ui'

export function AlertsView({ safety }: SafetyCommonProps) {
  const all = safety.alerts
  const active = all.filter(a => !a.resolved)
  const resolved = all.filter(a => a.resolved)

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel
        title="Active Alerts"
        right={
          <span className="font-mono text-sm font-bold text-on-surface">{active.length}</span>
        }
      >
        {active.length === 0 ? (
          <Empty
            label={
              safety.offline
                ? 'Backend offline — polling.'
                : 'No active alerts. Alerts de-duplicate by root cause and escalate in place.'
            }
          />
        ) : (
          <ul className="mt-1 space-y-2">
            {active.map(a => (
              <AlertCard key={a.id} alert={a} onAck={() => safety.ack(a.id)} />
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        title="Resolved Alert History"
        right={
          <span className="font-mono text-sm font-bold text-on-surface">{resolved.length}</span>
        }
      >
        {resolved.length === 0 ? (
          <Empty label="Nothing resolved yet." />
        ) : (
          <ul className="mt-1 space-y-2">
            {resolved.map(a => (
              <AlertCard key={a.id} alert={a} onAck={() => undefined} />
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}

function AlertCard({ alert, onAck }: { alert: SafetyAlert; onAck: () => void }) {
  const color = ALERT_COLORS[alert.level] ?? ALERT_COLORS.INFO
  return (
    <li
      className="border bg-surface-container-low p-3"
      style={{ borderColor: tint(color, 0.35), borderLeftWidth: 3, borderLeftColor: color }}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-xs font-bold uppercase tracking-wider" style={{ color }}>
          {alert.level} — {alert.title}
        </p>
        <Badge color={color}>{alert.event_type.replace(/_/g, ' ')}</Badge>
      </div>
      <p className="mt-1 font-mono text-[11px] text-on-surface">{alert.message}</p>
      <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
        {alert.object ?? '—'} ·conf {riskPercent(alert.confidence)} · raised{' '}
        {formatTimestamp(alert.created_at)}
        {alert.acknowledged ? ` · acked ${formatTimestamp(alert.acked_at ?? alert.updated_at)}` : ''}
        {alert.resolved ? ` · resolved ${formatTimestamp(alert.resolved_at ?? alert.updated_at)}` : ''}
      </p>
      {alert.recommended_action && (
        <p className="mt-1 font-mono text-[11px]" style={{ color }}>
          ACTION: {alert.recommended_action}
        </p>
      )}
      {!alert.resolved && !alert.acknowledged && (
        <button type="button" onClick={onAck} className="btn-outline mt-2">
          Acknowledge
        </button>
      )}
      {!alert.resolved && alert.acknowledged && (
        <p className="mt-2 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
          Acknowledged — operator responsible.
        </p>
      )}
    </li>
  )
}
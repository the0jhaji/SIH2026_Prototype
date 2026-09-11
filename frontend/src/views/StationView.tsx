import { ALERT_COLORS, type StationAlert } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import type { SafetyCommonProps } from './props'
import { Badge, Empty, Panel } from './ui'

export function StationView({ safety }: SafetyCommonProps) {
  const feed = safety.station
  return (
    <Panel
      title="Mission Control / Space Station Console"
      right={
        <span className="font-mono text-sm font-bold text-on-surface">{feed.length}</span>
      }
    >
      {feed.length === 0 ? (
        <Empty
          label={
            'No station alerts yet. Station alerts are delivered to the local console transport — nothing is transmitted off-board.'
          }
        />
      ) : (
        <ul className="mt-1 space-y-2">
          {feed.map(a => (
            <StationRow key={a.id} alert={a} />
          ))}
        </ul>
      )}
    </Panel>
  )
}

function StationRow({ alert }: { alert: StationAlert }) {
  const color = ALERT_COLORS[alert.severity as keyof typeof ALERT_COLORS] ?? ALERT_COLORS.INFO
  return (
    <li
      className="flex items-start gap-3 border border-outline-variant/30 bg-surface-container-low p-3"
      style={{ borderLeftWidth: 3, borderLeftColor: color }}
    >
      <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
      <div className="min-w-0">
        <p className="font-mono text-xs font-bold uppercase tracking-wider" style={{ color }}>
          {alert.title}
        </p>
        <p className="mt-0.5 font-mono text-[11px] text-on-surface">{alert.message}</p>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
          {alert.event_type} · {alert.incident_id ?? 'no incident'} ·{' '}
          {formatTimestamp(alert.timestamp)}
        </p>
      </div>
      <span className="ml-auto shrink-0">
        <Badge color={color}>{alert.confidence > 0 ? `${Math.round(alert.confidence * 100)}%` : '—'}</Badge>
      </span>
    </li>
  )
}
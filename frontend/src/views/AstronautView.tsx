import { ALERT_COLORS, MISSION_COLORS, tint } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import type { SafetyCommonProps } from './props'
import { Badge, Empty, KeyValue, Panel, StatTile } from './ui'

export function AstronautView({ safety }: SafetyCommonProps) {
  const snapshot = safety.snapshot
  const box = snapshot?.astronaut_box ?? null
  const emergency = snapshot?.emergency ?? null
  const emergencyStatus = safety.status?.emergency ?? null
  const monitor = snapshot?.monitor ?? null
  const stateColor = MISSION_COLORS[snapshot?.mission_state ?? 'NORMAL']

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Panel title="Crew Member in View">
        {snapshot?.astronaut_in_view && box ? (
          <div className="space-y-2">
            <Badge color="#22c55e" pulse>
              In view
            </Badge>
            <div className="grid grid-cols-2 gap-2">
              <StatTile label="Confidence" value={`${Math.round(box.confidence * 100)}%`} />
              <StatTile label="Box" value={`${box.x2 - box.x1} × ${box.y2 - box.y1}`} />
            </div>
            <KeyValue label="X range" value={`${box.x1} – ${box.x2}`} />
            <KeyValue label="Y range" value={`${box.y1} – ${box.y2}`} />
          </div>
        ) : (
          <Empty
            label={
              snapshot?.feed_stale
                ? 'Feed is stale — last known scene retained; nothing new is claimed.'
                : 'No crew member detected in frame.'
            }
          />
        )}
      </Panel>

      <Panel
        title="Emergency Monitor"
        right={
          <span className="font-mono text-[10px] uppercase text-on-surface-variant">
            backend: {emergencyStatus?.backend ?? '—'}
          </span>
        }
      >
        {emergency ? (
          <div
            className="border px-3 py-2"
            style={{
              borderColor: emergency.confirmed
                ? ALERT_COLORS.EMERGENCY
                : ALERT_COLORS.WARNING,
              background: tint(
                emergency.confirmed ? ALERT_COLORS.EMERGENCY : ALERT_COLORS.WARNING,
                0.08,
              ),
            }}
          >
            <p
              className="font-mono text-xs font-bold uppercase tracking-wider"
              style={{
                color: emergency.confirmed ? ALERT_COLORS.EMERGENCY : ALERT_COLORS.WARNING,
              }}
            >
              {emergency.confirmed ? 'CONFIRMED — ' : 'CANDIDATE — '}
              {emergency.event_type}
            </p>
            <p className="mt-1 font-mono text-[11px] text-on-surface">{emergency.description}</p>
            {emergency.recommended_action && (
              <p className="mt-1 font-mono text-[11px] text-on-surface">
                ACTION: {emergency.recommended_action}
              </p>
            )}
            <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
              conf {Math.round(emergency.confidence * 100)}% · {emergency.source} ·{' '}
              {formatTimestamp(emergency.timestamp)}
            </p>
          </div>
        ) : (
          <Empty label="No emergency signal. The rules backend tracks absence, stillness and collision cues over consecutive frames." />
        )}
        <div className="mt-3 grid grid-cols-3 gap-2">
          <StatTile label="Absent fr" value={String(emergencyStatus?.absentFrames ?? 0)} />
          <StatTile label="Static fr" value={String(emergencyStatus?.staticFrames ?? 0)} />
          <StatTile label="Tick" value={String(emergencyStatus?.tick ?? 0)} />
        </div>
      </Panel>

      <Panel title="Monitor State Machine">
        {monitor ? (
          <>
            <Badge color={stateColor} pulse={monitor.state !== 'NORMAL'}>
              {monitor.state}
            </Badge>
            <div className="mt-3 space-y-1.5">
              <KeyValue label="State index" value={String(monitor.stateIndex)} />
              <KeyValue
                label="Active since"
                value={monitor.activeSince ? formatTimestamp(monitor.activeSince) : '—'}
              />
              <KeyValue label="Acked level" value={String(monitor.ackedLevel)} />
            </div>
            <p className="mt-3 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
              NORMAL → OBSERVING → CAUTION → WARNING → CRITICAL → EMERGENCY, resolves only
              on fresh frames.
            </p>
          </>
        ) : (
          <Empty label="No monitor snapshot yet." />
        )}
      </Panel>
    </div>
  )
}
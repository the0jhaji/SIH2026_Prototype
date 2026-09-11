import { CAMERA_STREAM_URL } from '../domain/camera'
import {
  ALERT_COLORS,
  MISSION_COLORS,
  RISK_COLORS,
  riskPercent,
  safeCount,
  safePercent,
  tint,
  type HazardAssessment,
} from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import { LiveCameraFeed } from '../components/LiveFeed'
import type { SafetyCommonProps } from './props'
import { Badge, Empty, KeyValue, Panel, StatTile } from './ui'

export function MissionView({
  cameraRunning,
  cameraOffline,
  onCameraStart,
  onCameraStop,
  safety,
  detection,
}: SafetyCommonProps) {
  const snapshot = safety.snapshot
  const assessment = snapshot?.top_hazard ?? null
  const monitorState = snapshot?.mission_state ?? 'NORMAL'
  const stateColor = MISSION_COLORS[monitorState]
  const riskColor = RISK_COLORS[snapshot?.overall_risk_level ?? 'SAFE']
  const emergency = snapshot?.emergency ?? null
  const activeAlerts = safety.alerts.filter(a => !a.resolved && !a.acknowledged)
  const stale = snapshot?.feed_stale ?? false
  const streamUrl = cameraRunning ? CAMERA_STREAM_URL : null
  const detections = cameraRunning ? detection.result?.detections ?? [] : []
  const frameW = cameraRunning ? detection.result?.frameWidth ?? null : null
  const frameH = cameraRunning ? detection.result?.frameHeight ?? null : null

  return (
    <div className="space-y-4">
      {/* Mission status banner */}
      <section
        className="panel relative overflow-hidden border-l-4 p-4"
        style={{ borderLeftColor: stateColor }}
      >
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div
              className="flex h-14 w-14 items-center justify-center rounded-full border-2 font-mono text-[10px] font-bold leading-tight"
              style={{
                borderColor: stateColor,
                color: stateColor,
                background: tint(stateColor, 0.08),
              }}
            >
              {monitorState.replace(/_/g, ' ')}
            </div>
            <div>
              <p className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                Mission state · overall risk
              </p>
              <p className="font-mono text-xl font-bold" style={{ color: riskColor }}>
                {snapshot?.overall_risk_level ?? 'SAFE'}{' '}
                <span className="text-sm text-on-surface-variant">
                  · {snapshot?.assessments?.length ?? 0} assessed · {safeCount(snapshot?.assessments)} safe
                </span>
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Badge color={snapshot?.monitoring ? MISSION_COLORS.NORMAL : '#64748b'}>
              {snapshot?.monitoring ? 'MONITORING' : 'MONITOR OFF'}
            </Badge>
            <Badge color={stale ? '#f97316' : '#64748b'} pulse={stale}>
              {stale ? 'STALE FEED' : 'FEED FRESH'}
            </Badge>
            <Badge color="#38bdf8">{snapshot?.environment_mode ?? '—'}</Badge>
            <Badge color="#a78bfa">{snapshot?.model_version ?? 'unknown'}</Badge>
          </div>
        </div>

        {emergency && (
          <div
            className="mt-3 border px-3 py-2"
            style={{
              borderColor: ALERT_COLORS.EMERGENCY,
              background: tint(ALERT_COLORS.EMERGENCY, 0.08),
            }}
          >
            <p
              className="flex items-center gap-2 font-mono text-xs font-bold uppercase tracking-wider"
              style={{ color: emergency.confirmed ? ALERT_COLORS.EMERGENCY : '#f59e0b' }}
            >
              {emergency.confirmed ? 'CONFIRMED' : 'CANDIDATE'} EMERGENCY — {emergency.event_type}
            </p>
            <p className="mt-1 font-mono text-xs text-on-surface">
              {emergency.description}
              {emergency.recommended_action ? ` · ${emergency.recommended_action}` : ''}
            </p>
          </div>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Panel
            title="Live Camera Feed"
            right={
              <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                CAM-01 · {cameraRunning ? 'LIVE' : 'STANDBY'}
              </span>
            }
          >
            {cameraRunning ? (
              <LiveCameraFeed
                streamUrl={streamUrl ?? ''}
                detections={detections}
                frameWidth={frameW}
                frameHeight={frameH}
              />
            ) : (
              <div className="flex aspect-video w-full items-center justify-center border border-outline-variant/30 bg-surface-container-low">
                <p className="font-mono text-xs uppercase tracking-widest text-on-surface-variant">
                  {cameraOffline
                    ? 'CAMERA OFFLINE'
                    : 'No camera feed — press CAM ON to start the visual monitor'}
                </p>
              </div>
            )}
            <div className="mt-3 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={onCameraStart}
                disabled={cameraRunning || cameraOffline}
                className="btn-primary"
              >
                CAM ON
              </button>
              <button
                type="button"
                onClick={onCameraStop}
                disabled={!cameraRunning}
                className="btn-outline"
              >
                CAM OFF
              </button>
            </div>
          </Panel>

          <Panel
            title="Top Hazard"
            right={
              snapshot?.top_hazard ? (
                <Badge color={riskColor}>{snapshot.overall_risk_level}</Badge>
              ) : null
            }
          >
            {assessment ? <HazardCard assessment={assessment} /> : <Empty label="No hazard in view." />}
          </Panel>
        </div>

        <div className="space-y-4">
          <Panel title="Astronaut Status">
            <div className="mt-2">
              <KeyValue
                label="In view"
                value={snapshot?.astronaut_in_view ? 'YES' : 'NO'}
                color={snapshot?.astronaut_in_view ? MISSION_COLORS.NORMAL : '#64748b'}
              />
              {snapshot?.astronaut_box ? (
                <>
                  <KeyValue
                    label="Confidence"
                    value={riskPercent(snapshot.astronaut_box.confidence)}
                  />
                  <KeyValue
                    label="Position"
                    value={`x ${snapshot.astronaut_box.x1}–${snapshot.astronaut_box.x2} · y ${snapshot.astronaut_box.y1}–${snapshot.astronaut_box.y2}`}
                  />
                </>
              ) : null}
              <KeyValue label="Emergency" value={emergency?.event_type ?? 'none'} color={emergency ? '#ef4444' : undefined} />
            </div>
          </Panel>

          <Panel
            title="Active Alerts"
            right={<span className="font-mono text-sm font-bold text-on-surface">{activeAlerts.length}</span>}
          >
            {activeAlerts.length === 0 ? (
              <Empty label="No active alerts." />
            ) : (
              <ul className="mt-1 space-y-1.5">
                {activeAlerts.slice(0, 4).map(a => (
                  <li
                    key={a.id}
                    className="flex items-center justify-between border border-outline-variant/30 bg-surface-container-low px-2.5 py-1.5"
                  >
                    <span className="font-mono text-[11px] font-bold uppercase tracking-wider">
                      {a.object ?? a.event_type.replace(/_/g, ' ')}
                    </span>
                    <Badge color={ALERT_COLORS[a.level]}>{a.level}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Assessment Quick View">
            <div className="grid grid-cols-2 gap-2">
              <StatTile label="Objects" value={String(snapshot?.assessments?.length ?? 0)} />
              <StatTile
                label="Safe"
                value={safePercent(snapshot?.assessments)}
                color={riskColor}
              />
              <StatTile
                label="Hazards"
                value={String(snapshot?.assessments?.filter(a => a.hazard)?.length ?? 0)}
                color={riskColor}
              />
              <StatTile label="Unclassified" value={String(snapshot?.unclassified?.length ?? 0)} />
              <StatTile label="Incidents" value={String(safety.incidents.length)} />
              <StatTile label="Escalations" value={String(safety.status?.escalations_ready ?? 0)} />
            </div>
          </Panel>

          <Panel
            title="Monitor"
            right={
              <span className="font-mono text-[10px] uppercase text-on-surface-variant">
                state #{snapshot?.monitor.stateIndex ?? 0}
              </span>
            }
          >
            {snapshot?.monitor ? (
              <>
                <KeyValue label="State" value={snapshot.monitor.state} color={stateColor} />
                <KeyValue
                  label="Active since"
                  value={
                    snapshot.monitor.activeSince
                      ? formatTimestamp(snapshot.monitor.activeSince)
                      : '—'
                  }
                />
                <KeyValue label="Detector" value={snapshot.detector ?? '—'} />
                <KeyValue
                  label="Inference"
                  value={detection.result?.inferenceStatus ?? '—'}
                  color={detection.result?.inferenceStatus === 'ok' ? '#22c55e' : '#f97316'}
                />
                {detection.result?.error && (
                  <p className="mt-2 border border-error/40 bg-error/10 px-2 py-1 font-mono text-[11px] text-error">
                    AI ENGINE ERROR: {detection.result.error}
                  </p>
                )}
              </>
            ) : (
              <Empty label={safety.offline ? 'Backend offline — polling.' : 'No mission snapshot yet.'} />
            )}
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={safety.start}
                disabled={snapshot?.monitoring || safety.busy}
                className="btn-primary"
              >
                MONITOR ON
              </button>
              <button
                type="button"
                onClick={safety.stop}
                disabled={!snapshot?.monitoring || safety.busy}
                className="btn-outline"
              >
                MONITOR OFF
              </button>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}

export function HazardCard({ assessment }: { assessment: HazardAssessment }) {
  const color = RISK_COLORS[assessment.risk_level] ?? '#64748b'
  const proximity = assessment.proximity
  return (
    <div className="border border-outline-variant/30 bg-surface-container-low p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-sm font-bold uppercase tracking-wider">
            {assessment.object.replace(/_/g, ' ')}
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-on-surface-variant">
            {assessment.hazard_type ?? 'unclassified'} · conf {riskPercent(assessment.confidence)}
          </p>
        </div>
        <Badge color={color} pulse={assessment.confirmed && assessment.risk_level !== 'SAFE'}>
          {assessment.risk_level} {riskPercent(assessment.risk_score)}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 font-mono text-[10px] uppercase tracking-wider">
        <Badge color={assessment.confirmed ? '#22c55e' : '#facc15'}>
          {assessment.confirmed ? 'CONFIRMED' : 'CANDIDATE'}
        </Badge>
        <Badge color={proximity === 'NEAR' ? '#f97316' : '#64748b'}>
          {proximity === 'UNKNOWN_ASTRONAUT' ? 'PROXIMITY: NO CREW IN VIEW' : `PROXIMITY: ${proximity}`}
        </Badge>
        {assessment.moving_toward_astronaut && (
          <Badge color="#ef4444">MOVING TOWARD CREW</Badge>
        )}
        <Badge color="#64748b">{assessment.frames_persisted} frames</Badge>
      </div>
      <p className="mt-2 font-mono text-[11px] text-on-surface-variant">{assessment.reason}</p>
      {assessment.recommended_action && (
        <p className="mt-1 font-mono text-[11px]" style={{ color }}>
          ACTION: {assessment.recommended_action}
        </p>
      )}
    </div>
  )
}
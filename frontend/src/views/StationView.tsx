import { useMemo } from 'react'
import { ALERT_COLORS, MISSION_COLORS, type StationAlert } from '../domain/safety'
import { expectedStep } from '../domain/experiment'
import { voiceStateDetail, voiceStateLabel } from '../domain/voice'
import { formatTimestamp } from '../lib/time'
import { Badge, EmptyState, KeyValue, MetricCard, Panel, StatTile, SubCard } from './ui'
import { PageShell, Timeline } from './layout'
import { safetyEventEntries, stateColor } from './helpers'
import { useCamera } from '../hooks/cameraController'
import { CAMERA_PHASE_LABEL } from '../domain/camera'
import type { SafetyCommonProps } from './props'

/**
 * Station overview.
 *
 * The backend exposes no independent station telemetry bus, so this view is
 * assembled from the subsystems that *are* connected — camera, detector,
 * safety monitor, experiment engine — and every panel that would need a
 * source we do not have says so explicitly rather than showing a zero that
 * reads like a measurement.
 */
export function StationView({
  state,
  engine,
  engineOffline,
  safety,
  detection,
  attendance,
}: SafetyCommonProps) {
  const { phase: cameraPhase, streamActive: cameraRunning, info: camera } = useCamera()
  const snapshot = safety.snapshot
  const status = safety.status
  const feed = safety.station
  const expected = expectedStep(state.experiment, state.currentStepIndex)
  const timeline = useMemo(() => safetyEventEntries(safety.events, 60), [safety.events])

  const experimentProgress = engine
    ? engine.total_steps > 0
      ? Math.round((engine.completed_count / engine.total_steps) * 100)
      : 0
    : state.experiment.steps.length > 0
      ? Math.round((state.completedStepIds.length / state.experiment.steps.length) * 100)
      : 0

  const systemWarnings = [
    detection.status?.error,
    detection.result?.error,
    safety.snapshot?.detector_error,
    engineOffline ? 'Experiment engine endpoint unreachable' : null,
  ].filter((v): v is string => Boolean(v))

  return (
    <PageShell>
      {/* ── Station status row ───────────────────────────────────── */}
      <div className="grid shrink-0 grid-cols-2 gap-[var(--grid-gap)] lg:grid-cols-4">
        <MetricCard
          label="Station status"
          value={safety.offline ? 'OFFLINE' : (snapshot?.mission_state ?? 'STANDBY')}
          sub={snapshot?.environment_mode ?? 'mode —'}
          color={stateColor(snapshot?.mission_state)}
          active={!safety.offline}
        />
        <MetricCard
          label="System health"
          value={systemWarnings.length === 0 ? 'NOMINAL' : `${systemWarnings.length} WARN`}
          sub={systemWarnings.length === 0 ? 'no subsystem errors' : 'see system health'}
          color={systemWarnings.length === 0 ? '#22c55e' : '#f97316'}
          active={systemWarnings.length > 0}
        />
        <MetricCard
          label="AI status"
          value={detection.result?.inferenceStatus ?? '—'}
          sub={`${detection.status?.detector ?? 'no detector'} · ${detection.status?.actualFps?.toFixed?.(1) ?? '—'} fps`}
          color={detection.result?.inferenceStatus === 'ok' ? '#22c55e' : '#f97316'}
          active={detection.result?.inferenceStatus === 'ok'}
        />
        <MetricCard
          label="Camera status"
          value={CAMERA_PHASE_LABEL[cameraPhase]}
          sub={cameraRunning ? `${camera?.width}×${camera?.height}` : 'start from the Camera view'}
          color={cameraRunning ? MISSION_COLORS.NORMAL : '#64748b'}
          active={cameraRunning}
        />
      </div>

      {/* ── Overview · mission status · station alerts ───────────── */}
      <div className="page-fill grid-cols-1 lg:grid-cols-3">
        <Panel
          title="Station Overview"
          fill
          scroll
          right={
            <Badge color={cameraRunning ? MISSION_COLORS.NORMAL : '#64748b'}>
              {cameraRunning ? 'Feeds active' : 'Feeds idle'}
            </Badge>
          }
        >
          <div className="stack">
            <SubCard title="Active station">
              <KeyValue label="Environment" value={snapshot?.environment_mode ?? '—'} />
              <KeyValue label="Model version" value={snapshot?.model_version ?? '—'} />
              <KeyValue label="Detector" value={snapshot?.detector ?? '—'} />
              <KeyValue
                label="Feed"
                value={snapshot?.feed_stale ? 'stale' : 'fresh'}
                color={snapshot?.feed_stale ? '#f97316' : MISSION_COLORS.NORMAL}
              />
            </SubCard>
            <SubCard title="Camera feeds">
              <KeyValue
                label="CAM-01"
                value={CAMERA_PHASE_LABEL[cameraPhase]}
                color={cameraRunning ? MISSION_COLORS.NORMAL : '#64748b'}
              />
              <KeyValue
                label="Resolution"
                value={camera ? `${camera.width}×${camera.height}` : '—'}
              />
              <KeyValue
                label="Detections"
                value={String(detection.result?.detections.length ?? 0)}
              />
              <KeyValue
                label="Unknown objects"
                value={String(detection.result?.unknownDetections.length ?? 0)}
              />
            </SubCard>
            <SubCard title="Environment status">
              <KeyValue
                label="Risk level"
                value={snapshot?.overall_risk_level ?? '—'}
                color={snapshot ? MISSION_COLORS.OBSERVING : '#64748b'}
              />
              <KeyValue label="Crew in view" value={snapshot?.astronaut_in_view ? 'yes' : 'no'} />
              <KeyValue
                label="Unattended"
                value={String(attendance.status?.unattendedCount ?? 0)}
                color={(attendance.status?.unattendedCount ?? 0) > 0 ? '#ef4444' : undefined}
              />
              <KeyValue
                label="Assessed objects"
                value={String(snapshot?.assessments?.length ?? 0)}
              />
            </SubCard>
          </div>
        </Panel>

        <Panel
          title="Mission / Experiment Status"
          fill
          scroll
          right={
            <Badge color={state.status === 'RUNNING' ? MISSION_COLORS.NORMAL : '#64748b'}>
              {state.status}
            </Badge>
          }
        >
          <div className="stack">
            <SubCard title="Current experiment">
              <p className="font-mono text-sm font-semibold">
                {engine?.experiment_name ?? state.experiment.name}
              </p>
              <p className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
                {engine?.run_id ? `run ${engine.run_id}` : state.experiment.id}
              </p>
            </SubCard>
            <SubCard
              title="Progress"
              right={
                <span className="font-mono text-[10px] text-on-surface-variant">
                  {engine
                    ? `${engine.completed_count}/${engine.total_steps}`
                    : `${state.completedStepIds.length}/${state.experiment.steps.length}`}
                </span>
              }
            >
              <div className="h-1.5 w-full bg-surface-container-high">
                <div
                  className="h-full transition-all"
                  style={{ width: `${experimentProgress}%`, background: 'var(--color-primary)' }}
                />
              </div>
              <p className="mt-1 font-mono text-[10px] text-on-surface-variant">
                {experimentProgress}% of the procedure matched
              </p>
            </SubCard>
            <SubCard title="Current step">
              {engine?.current_step ? (
                <>
                  <p className="font-mono text-[11px] font-semibold">{engine.current_step.label}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
                    {engine.current_step.activity}
                  </p>
                </>
              ) : expected ? (
                <>
                  <p className="font-mono text-[11px] font-semibold">{expected.label}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
                    {expected.activity}
                  </p>
                </>
              ) : (
                <p className="font-mono text-[10px] text-on-surface-variant">
                  Procedure complete — no step is expected.
                </p>
              )}
            </SubCard>
            <SubCard title="Activity">
              <p className="font-mono text-[11px] uppercase tracking-wider">
                {state.currentDetected?.activity?.replace(/_/g, ' ') ?? 'None interpreted'}
              </p>
              <p className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
                Voice {voiceStateLabel(engine?.voice)} · {voiceStateDetail(engine?.voice)}
              </p>
            </SubCard>
          </div>
        </Panel>

        <Panel
          title="Station Alerts"
          fill
          scroll
          right={
            <span className="font-mono text-xs font-bold text-on-surface">{feed.length}</span>
          }
        >
          {feed.length === 0 ? (
            <div className="stack">
              <EmptyState
                icon="router"
                title="No station alerts"
                description="Station alerts are delivered to the local console transport — nothing is transmitted off-board."
                lastUpdated={
                  snapshot?.timestamp ? `Last assessment ${formatTimestamp(snapshot.timestamp)}` : undefined
                }
              />
              <SubCard title="Console transport">
                <p className="font-mono text-[10px] leading-snug text-on-surface-variant">
                  The station feed is a local queue served from /api/safety/station. There is no
                  network link to a ground segment, so an empty queue means nothing has been raised
                  locally — not that anything was delivered elsewhere.
                </p>
              </SubCard>
            </div>
          ) : (
            <ul className="rows">
              {feed.map(a => (
                <StationRow key={a.id} alert={a} />
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {/* ── System health + event timeline ───────────────────────── */}
      <div
        className="page-fill shrink-0 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]"
        style={{ height: 'var(--strip-h)', flex: 'none' }}
      >
        <Panel
          title="System Health"
          fill
          scroll
          right={
            <Badge color={systemWarnings.length ? '#f97316' : '#22c55e'}>
              {systemWarnings.length ? `${systemWarnings.length} warnings` : 'Nominal'}
            </Badge>
          }
        >
          <div className="stack">
            <div className="grid grid-cols-2 gap-[var(--row-pad)] sm:grid-cols-4">
              <StatTile
                label="Safety tick"
                value={status ? String(status.tick) : '—'}
                title="Safety monitor evaluation counter"
              />
              <StatTile label="Alerts active" value={String(status?.alerts_active ?? 0)} />
              <StatTile label="Incidents open" value={String(status?.incidents_open ?? 0)} />
              <StatTile
                label="Escalations"
                value={String(status?.escalations_ready ?? 0)}
                color={(status?.escalations_ready ?? 0) > 0 ? '#facc15' : undefined}
              />
            </div>
            {systemWarnings.length > 0 ? (
              <ul className="rows">
                {systemWarnings.map((w, i) => (
                  <li
                    key={`${w}-${i}`}
                    className="border border-warning/40 bg-warning/10 px-2 py-1 font-mono text-[10px] text-warning"
                  >
                    {w}
                  </li>
                ))}
              </ul>
            ) : (
              <SubCard title="No subsystem warnings">
                <p className="font-mono text-[10px] leading-snug text-on-surface-variant">
                  Camera, detector, safety monitor and experiment engine all report healthy or idle
                  states.
                </p>
              </SubCard>
            )}
            <SubCard title="Telemetry">
              <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
                Telemetry unavailable
              </p>
              <p className="mt-0.5 font-mono text-[10px] leading-snug text-on-surface-variant">
                No live station telemetry source is connected. This console aggregates the local
                camera, detection, safety and experiment subsystems only — power, thermal, attitude
                and consumables are not instrumented, and nothing on this screen is simulated to
                fill the gap.
              </p>
            </SubCard>
          </div>
        </Panel>

        <Panel
          title="Event Timeline"
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
                title="No station events"
                description="Safety, detection and attendance transitions are recorded here in order."
              />
            }
          />
        </Panel>
      </div>
    </PageShell>
  )
}

function StationRow({ alert }: { alert: StationAlert }) {
  const color = ALERT_COLORS[alert.severity as keyof typeof ALERT_COLORS] ?? ALERT_COLORS.INFO
  return (
    <li
      className="flex items-start gap-2 border border-outline-variant/30 bg-surface-container-low p-2"
      style={{ borderLeftWidth: 3, borderLeftColor: color }}
    >
      <span className="mt-1 h-1.5 w-1.5 shrink-0" style={{ background: color }} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[11px] font-bold uppercase tracking-wider" style={{ color }}>
          {alert.title}
        </p>
        <p className="font-mono text-[10px] text-on-surface">{alert.message}</p>
        <p className="truncate font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
          {alert.event_type} · {alert.incident_id ?? 'no incident'} · {alert.source} ·{' '}
          {formatTimestamp(alert.timestamp)}
        </p>
      </div>
      <span className="shrink-0">
        <Badge color={color}>{alert.confidence > 0 ? `${Math.round(alert.confidence * 100)}%` : '—'}</Badge>
      </span>
    </li>
  )
}

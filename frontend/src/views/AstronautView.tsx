import { useMemo } from 'react'
import { ALERT_COLORS, MISSION_COLORS, riskPercent, tint } from '../domain/safety'
import { formatTimestamp } from '../lib/time'
import { Badge, EmptyState, KeyValue, MetricCard, Panel, StatTile, SubCard } from './ui'
import { PageShell, Timeline } from './layout'
import {
  attendanceEventEntries,
  safetyEventEntries,
  severityColor,
  stateColor,
} from './helpers'
import { useCamera } from '../hooks/cameraController'
import { CAMERA_PHASE_LABEL } from '../domain/camera'
import type { SafetyCommonProps } from './props'

/**
 * Crew view.
 *
 * The backend reports at most one crew box per frame, so this is not a
 * roster — it is the status of the crew member it currently sees, the
 * emergency rules state, and the presence/attention history that explains
 * it. When nobody is visible the panel says so and shows the camera and
 * monitoring state that would be needed to change that.
 */
export function AstronautView({
  safety,
  detection,
  attendance,
}: SafetyCommonProps) {
  const { phase: cameraPhase, streamActive: cameraRunning } = useCamera()
  const snapshot = safety.snapshot
  const box = snapshot?.astronaut_box ?? null
  const emergency = snapshot?.emergency ?? null
  const emergencyStatus = safety.status?.emergency ?? null
  const monitor = snapshot?.monitor ?? null
  const tone = stateColor(snapshot?.mission_state ?? 'NORMAL')
  const inView = Boolean(snapshot?.astronaut_in_view && box)
  const timeline = useMemo(() => safetyEventEntries(safety.events, 60), [safety.events])
  const personEvents = useMemo(
    () =>
      attendanceEventEntries(attendance.result?.events, 60).filter(e =>
        /astronaut|person|crew|proximity|absence|stillness|unobserved|down/i.test(
          `${e.title} ${e.detail ?? ''} ${e.meta ?? ''}`,
        ),
      ),
    [attendance.result?.events],
  )

  return (
    <PageShell>
      {/* ── Crew overview ────────────────────────────────────────── */}
      <div className="grid shrink-0 grid-cols-2 gap-[var(--grid-gap)] lg:grid-cols-4">
        <MetricCard
          label="Crew in view"
          value={inView ? 'YES' : 'NO'}
          sub={inView ? `conf ${riskPercent(box?.confidence ?? 0)}` : 'no person in frame'}
          color={inView ? MISSION_COLORS.NORMAL : '#64748b'}
          active={inView}
        />
        <MetricCard
          label="Monitoring"
          value={snapshot?.monitoring ? 'ACTIVE' : 'OFF'}
          sub={snapshot?.feed_stale ? 'feed stale' : snapshot?.environment_mode ?? '—'}
          color={snapshot?.monitoring ? MISSION_COLORS.OBSERVING : '#64748b'}
          active={Boolean(snapshot?.monitoring)}
        />
        <MetricCard
          label="Emergency"
          value={emergency ? (emergency.confirmed ? 'CONFIRMED' : 'CANDIDATE') : 'NONE'}
          sub={emergency ? emergency.event_type.replace(/_/g, ' ') : 'absence · stillness · collision'}
          color={emergency ? (emergency.confirmed ? ALERT_COLORS.EMERGENCY : ALERT_COLORS.WARNING) : RISK_SAFE}
          active={Boolean(emergency)}
        />
        <MetricCard
          label="Crew alerts"
          value={String(
            safety.alerts.filter(a => /astronaut|emergency|absence|unobserved|down/i.test(a.event_type)).length,
          )}
          sub={`${safety.status?.alerts_active ?? 0} alerts active`}
          color={safety.status?.alerts_active ? '#ef4444' : RISK_SAFE}
          active={(safety.status?.alerts_active ?? 0) > 0}
        />
      </div>

      {/* ── Crew member + emergency monitor ──────────────────────── */}
      <div className="page-fill grid-cols-1 lg:grid-cols-[minmax(0,1.85fr)_minmax(0,1fr)]">
        <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="Crew Member in View"
            fill
            scroll
            right={
              inView ? (
                <Badge color={MISSION_COLORS.NORMAL} pulse>
                  In view
                </Badge>
              ) : null
            }
          >
            {inView && box ? (
              <div className="stack">
                <div className="grid grid-cols-2 gap-[var(--row-pad)] sm:grid-cols-4">
                  <StatTile
                    label="Confidence"
                    value={riskPercent(box.confidence)}
                    color={MISSION_COLORS.NORMAL}
                  />
                  <StatTile label="Box" value={`${box.x2 - box.x1} × ${box.y2 - box.y1}`} />
                  <StatTile
                    label="Position"
                    value={`${box.x1},${box.y1}`}
                    title="Top-left of the box in detection-frame pixels"
                  />
                  <StatTile
                    label="Emergency"
                    value={emergency ? emergency.event_type.replace(/_/g, ' ') : 'none'}
                    color={emergency ? ALERT_COLORS.EMERGENCY : undefined}
                  />
                </div>
                <div className="grid grid-cols-1 gap-[var(--row-pad)] sm:grid-cols-2">
                  <SubCard title="Current activity">
                    <p className="font-mono text-[11px] font-semibold uppercase tracking-wider">
                      {emergency ? emergency.event_type.replace(/_/g, ' ') : 'Not interpreted'}
                    </p>
                    <p className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
                      {emergency
                        ? 'Activity classification is owned by the perception layer; ASTRA reports the last confirmed interpretation.'
                        : 'No activity model is wired to the crew box yet — only presence is reported.'}
                    </p>
                  </SubCard>
                  <SubCard title="Interaction">
                    {attendance.result?.watches && attendance.result.watches.length > 0 ? (
                      <ul className="rows">
                        {attendance.result.watches.slice(0, 4).map(w => (
                          <li key={w.instanceId} className="truncate font-mono text-[10px]">
                            <span className="font-semibold uppercase tracking-wider">
                              {w.className.replace(/_/g, ' ')}
                            </span>{' '}
                            <span className="text-on-surface-variant">
                              {w.personId ? `held by ${w.personId}` : 'no crew associated'}
                              {w.personFreeMs > 0 ? ` · free ${Math.round(w.personFreeMs)}ms` : ''}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="font-mono text-[10px] text-on-surface-variant">
                        No object is currently associated with this crew member.
                      </p>
                    )}
                  </SubCard>
                </div>
                <div className="grid grid-cols-1 gap-[var(--row-pad)] sm:grid-cols-2">
                  <SubCard title="Status">
                    <KeyValue label="Mission state" value={snapshot?.mission_state ?? '—'} color={tone} />
                    <KeyValue label="Monitor" value={monitor?.state ?? '—'} color={tone} />
                    <KeyValue label="Since" value={monitor?.activeSince ? formatTimestamp(monitor.activeSince) : '—'} />
                    <KeyValue label="Ack level" value={String(monitor?.ackedLevel ?? 0)} />
                  </SubCard>
                  <SubCard title="Risk">
                    <KeyValue
                      label="Overall"
                      value={snapshot?.overall_risk_level ?? '—'}
                      color={severityColor(snapshot?.overall_risk_level)}
                    />
                    <KeyValue
                      label="Score"
                      value={riskPercent(snapshot?.overall_risk_score ?? 0)}
                    />
                    <KeyValue
                      label="Near hazards"
                      value={String((snapshot?.assessments ?? []).filter(a => a.near_astronaut).length)}
                      color={(snapshot?.assessments ?? []).some(a => a.near_astronaut) ? '#f97316' : undefined}
                    />
                    <KeyValue
                      label="Last seen"
                      value={snapshot?.timestamp ? formatTimestamp(snapshot.timestamp) : '—'}
                    />
                  </SubCard>
                </div>
              </div>
            ) : (
              <EmptyState
                icon="person_off"
                title="No crew member currently in view"
                description={
                  snapshot?.feed_stale
                    ? 'The feed is stale (camera stopped). The last known scene is retained and nothing new is claimed.'
                    : 'The camera is active but no crew member is currently visible.'
                }
                status={CAMERA_PHASE_LABEL[cameraPhase]}
                lastUpdated={
                  snapshot?.timestamp ? `Last seen ${formatTimestamp(snapshot.timestamp)}` : undefined
                }
              />
            )}
          </Panel>

          <Panel title="Monitoring Status" className="shrink-0">
            <div className="grid grid-cols-2 gap-[var(--row-pad)] sm:grid-cols-4">
              <StatTile
                label="Camera"
                value={CAMERA_PHASE_LABEL[cameraPhase]}
                color={cameraRunning ? MISSION_COLORS.NORMAL : '#64748b'}
              />
              <StatTile
                label="Safety monitor"
                value={snapshot?.monitoring ? 'on' : 'off'}
                color={snapshot?.monitoring ? MISSION_COLORS.NORMAL : '#64748b'}
              />
              <StatTile
                label="Detector"
                value={detection.status?.detector ?? '—'}
              />
              <StatTile
                label="Inference"
                value={detection.result?.inferenceStatus ?? '—'}
                color={detection.result?.inferenceStatus === 'ok' ? MISSION_COLORS.NORMAL : '#f97316'}
              />
            </div>
          </Panel>
        </div>

        <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="Emergency Monitor"
            right={
              <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                backend {emergencyStatus?.backend ?? '—'}
              </span>
            }
          >
            {emergency ? (
              <div
                className="border px-2.5 py-1.5"
                style={{
                  borderColor: emergency.confirmed ? ALERT_COLORS.EMERGENCY : ALERT_COLORS.WARNING,
                  background: tint(
                    emergency.confirmed ? ALERT_COLORS.EMERGENCY : ALERT_COLORS.WARNING,
                    0.08,
                  ),
                }}
              >
                <p
                  className="font-mono text-[11px] font-bold uppercase tracking-wider"
                  style={{
                    color: emergency.confirmed ? ALERT_COLORS.EMERGENCY : ALERT_COLORS.WARNING,
                  }}
                >
                  {emergency.confirmed ? 'Confirmed' : 'Candidate'} — {emergency.event_type.replace(/_/g, ' ')}
                </p>
                <p className="mt-0.5 font-mono text-[11px] text-on-surface">{emergency.description}</p>
                {emergency.recommended_action && (
                  <p className="mt-0.5 font-mono text-[11px] text-on-surface">
                    Action: {emergency.recommended_action}
                  </p>
                )}
                <p className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                  conf {Math.round(emergency.confidence * 100)}% · {emergency.source} ·{' '}
                  {formatTimestamp(emergency.timestamp)}
                </p>
              </div>
            ) : (
              <EmptyState
                compact
                icon="health_and_safety"
                title="No emergency signal"
                description="The rules backend tracks absence, stillness and collision cues over consecutive frames."
              />
            )}
            <div className="mt-2 grid grid-cols-4 gap-[var(--row-pad)]">
              <StatTile label="Absent" value={String(emergencyStatus?.absentFrames ?? 0)} />
              <StatTile label="Static" value={String(emergencyStatus?.staticFrames ?? 0)} />
              <StatTile label="Present" value={String(emergencyStatus?.presentFrames ?? 0)} />
              <StatTile label="Tick" value={String(emergencyStatus?.tick ?? 0)} />
            </div>
          </Panel>

          <Panel
            title="Crew Activity Timeline"
            fill
            scroll
            right={
              <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                {personEvents.length > 0 ? `${personEvents.length} crew events` : `${timeline.length} events`}
              </span>
            }
          >
            {personEvents.length > 0 ? (
              <Timeline entries={personEvents} />
            ) : timeline.length > 0 ? (
              <div className="stack">
                <p className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                  No crew-specific event yet — showing all safety events
                </p>
                <Timeline entries={timeline} />
              </div>
            ) : (
              <EmptyState
                icon="timeline"
                title="No crew activity recorded"
                description="Crew-related safety transitions appear here as the rules backend raises them."
              />
            )}
          </Panel>
        </div>
      </div>

      {/* ── Bottom strip: monitor state + crew-facing alerts ─────── */}
      <div
        className="page-fill shrink-0 grid-cols-1 md:grid-cols-3"
        style={{ height: 'var(--strip-h)', flex: 'none' }}
      >
        <Panel title="Monitor State Machine" fill scroll>
          {monitor ? (
            <div className="stack">
              <div className="grid grid-cols-3 gap-[var(--row-pad)]">
                <StatTile label="State" value={monitor.state} color={tone} />
                <StatTile label="Index" value={String(monitor.stateIndex)} />
                <StatTile label="Acked" value={String(monitor.ackedLevel)} />
              </div>
              <KeyValue
                label="Active since"
                value={monitor.activeSince ? formatTimestamp(monitor.activeSince) : '—'}
              />
              <p className="font-mono text-[10px] leading-snug text-on-surface-variant">
                NORMAL → OBSERVING → CAUTION → WARNING → CRITICAL → EMERGENCY. It resolves only on
                fresh frames; a stale feed freezes the state rather than clearing it.
              </p>
            </div>
          ) : (
            <EmptyState compact icon="account_tree" title="No monitor snapshot" />
          )}
        </Panel>

        <Panel
          title="Crew Alerts"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {safety.alerts.filter(a => /astronaut|emergency|absence|unobserved|down/i.test(a.event_type)).length}
            </span>
          }
        >
          {safety.alerts.filter(a => /astronaut|emergency|absence|unobserved|down/i.test(a.event_type)).length ===
          0 ? (
            <EmptyState
              compact
              icon="notifications_off"
              title="No crew alerts"
              description="Nothing has been raised about crew presence or condition."
            />
          ) : (
            <ul className="rows">
              {safety.alerts
                .filter(a => /astronaut|emergency|absence|unobserved|down/i.test(a.event_type))
                .map(a => (
                  <li
                    key={a.id}
                    className="border px-2 py-1"
                    style={{ borderLeftWidth: 3, borderLeftColor: ALERT_COLORS[a.level] }}
                  >
                    <p className="truncate font-mono text-[11px] font-bold uppercase tracking-wider">
                      {a.level} — {a.title}
                    </p>
                    <p className="truncate font-mono text-[10px] text-on-surface-variant">
                      {a.message}
                    </p>
                  </li>
                ))}
            </ul>
          )}
        </Panel>

        <Panel
          title="Proximity Watch"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {(snapshot?.assessments ?? []).filter(a => a.near_astronaut).length} near
            </span>
          }
        >
          {(snapshot?.assessments ?? []).length === 0 ? (
            <EmptyState
              compact
              icon="person_search"
              title="No proximity data"
              description="Proximity needs both a crew box and an assessed object in the same frame."
            />
          ) : (
            <ul className="rows">
              {(snapshot?.assessments ?? []).map(a => (
                <li
                  key={`${a.object}-${a.timestamp}`}
                  className="flex items-center justify-between gap-2 border px-2 py-1"
                  style={{ borderLeftWidth: 3, borderLeftColor: severityColor(a.risk_level) }}
                >
                  <span className="min-w-0 truncate font-mono text-[11px] uppercase tracking-wider">
                    {a.object.replace(/_/g, ' ')}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                    {a.proximity === 'UNKNOWN_ASTRONAUT' ? 'no crew' : a.proximity.toLowerCase()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </PageShell>
  )
}

const RISK_SAFE = '#22c55e'

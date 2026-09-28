import { useMemo } from 'react'
import {
  ALERT_COLORS,
  MISSION_COLORS,
  RISK_COLORS,
  riskPercent,
  safeCount,
  tint,
  type HazardAssessment,
} from '../domain/safety'
import { hazardLevelsFrom, unattendedIdsFrom } from '../domain/detection'
import { expectedStep } from '../domain/experiment'
import { formatTimestamp } from '../lib/time'
import { CameraStage } from '../components/CameraStage'
import { useCamera } from '../hooks/cameraController'
import type { SafetyCommonProps } from './props'
import { Badge, Empty, EmptyState, KeyValue, Panel, StatTile, SubCard } from './ui'
import { PageShell, Timeline } from './layout'
import { attendanceEventEntries, safetyEventEntries, stateColor } from './helpers'

const ACTION_LABEL: Record<string, string> = {
  PICK: 'Pick',
  PLACE: 'Place',
  OPEN: 'Open',
}

/**
 * The command centre.
 *
 * Three rows: a fixed mission-summary strip, a fill row that takes the
 * remaining viewport (25 / 50 / 25 — the camera is the visual focus), and
 * a fixed bottom strip of event history, object tracking and AI
 * performance. Nothing here is padded to fill space: every panel is sized
 * by the values it actually holds.
 */
export function MissionView({
  state,
  engine,
  safety,
  detection,
  attendance,
}: SafetyCommonProps) {
  // The canonical camera state, read from the single controller rather than
  // from props this view recomputed for itself.
  const { streamActive, phase } = useCamera()
  const snapshot = safety.snapshot
  const topHazard = snapshot?.top_hazard ?? null
  const monitorState = snapshot?.mission_state ?? 'NORMAL'
  const stateTone = MISSION_COLORS[monitorState]
  const riskColor = RISK_COLORS[snapshot?.overall_risk_level ?? 'SAFE']
  const emergency = snapshot?.emergency ?? null
  const stale = snapshot?.feed_stale ?? false
  const activeAlerts = safety.alerts.filter(a => !a.resolved && !a.acknowledged)
  const acknowledgedAlerts = safety.alerts.filter(a => !a.resolved && a.acknowledged)

  const detections = streamActive ? (detection.result?.detections ?? []) : []
  const unknownDetections = streamActive ? (detection.result?.unknownDetections ?? []) : []
  const frameW = streamActive ? (detection.result?.frameWidth ?? null) : null
  const frameH = streamActive ? (detection.result?.frameHeight ?? null) : null
  const hazardLevels = useMemo(() => hazardLevelsFrom(snapshot?.assessments), [snapshot])
  const unattendedIds = useMemo(() => unattendedIdsFrom(attendance.result?.watches), [attendance])
  const safetyTimeline = useMemo(() => safetyEventEntries(safety.events, 60), [safety.events])
  const attendanceTimeline = useMemo(
    () => attendanceEventEntries(attendance.result?.events, 30),
    [attendance.result?.events],
  )

  const expected = expectedStep(state.experiment, state.currentStepIndex)
  const currentEngineStep = engine?.current_step ?? null
  const nextEngineStep = engine?.next_step ?? null
  const observed = state.currentDetected
  const classification = state.lastClassification
  const heldWatches = (attendance.result?.watches ?? []).filter(
    w => w.personId != null || w.state === 'HELD' || w.state === 'POSSIBLY_HELD',
  )

  return (
    <PageShell>
      {/* ── Mission summary ──────────────────────────────────────── */}
      <section
        className="panel shrink-0 border-l-4 px-3 py-2"
        style={{ borderLeftColor: stateTone }}
      >
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="flex min-w-0 items-center gap-3">
            <div
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border-2 text-center font-mono text-[9px] font-bold leading-tight"
              style={{
                borderColor: stateTone,
                color: stateTone,
                background: tint(stateTone, 0.08),
              }}
            >
              {monitorState.replace(/_/g, ' ')}
            </div>
            <div className="min-w-0">
              <p className="font-mono text-[9px] uppercase tracking-widest text-on-surface-variant">
                Mission state · overall risk
              </p>
              <p className="truncate font-mono text-lg font-bold" style={{ color: riskColor }}>
                {snapshot?.overall_risk_level ?? 'SAFE'}
                <span className="ml-2 text-[11px] font-normal text-on-surface-variant">
                  {snapshot?.assessments?.length ?? 0} assessed · {safeCount(snapshot?.assessments)} safe ·
                  risk {riskPercent(snapshot?.overall_risk_score ?? 0)}
                </span>
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <Badge color={snapshot?.monitoring ? MISSION_COLORS.NORMAL : '#64748b'}>
              {snapshot?.monitoring ? 'Monitoring' : 'Monitor off'}
            </Badge>
            <Badge color={stale ? '#f97316' : '#64748b'} pulse={stale}>
              {stale ? 'Stale feed' : 'Feed fresh'}
            </Badge>
            <Badge color="#38bdf8">{snapshot?.environment_mode ?? 'mode —'}</Badge>
            <Badge color="#a78bfa">{snapshot?.model_version ?? 'model —'}</Badge>
            <Badge color={activeAlerts.length ? '#ef4444' : '#64748b'}>
              {activeAlerts.length} active
            </Badge>
          </div>
        </div>

        {emergency && (
          <div
            className="mt-2 border px-2.5 py-1.5"
            style={{
              borderColor: ALERT_COLORS.EMERGENCY,
              background: tint(ALERT_COLORS.EMERGENCY, 0.08),
            }}
          >
            <p
              className="font-mono text-[11px] font-bold uppercase tracking-wider"
              style={{ color: emergency.confirmed ? ALERT_COLORS.EMERGENCY : '#f59e0b' }}
            >
              {emergency.confirmed ? 'Confirmed' : 'Candidate'} emergency — {emergency.event_type.replace(/_/g, ' ')}
            </p>
            <p className="font-mono text-[11px] text-on-surface">
              {emergency.description}
              {emergency.recommended_action ? ` · ${emergency.recommended_action}` : ''}
            </p>
          </div>
        )}
      </section>

      {/* ── Main row: procedure · camera · crew & risk ───────────── */}
      {/* Content-sized, not `page-fill`: the 16:9 camera sets this row's
          height, so the leftover viewport space goes to the bottom strip
          instead of stretching panels past their content into empty cards. */}
      <div className="grid min-h-0 shrink-0 grid-cols-1 gap-[var(--grid-gap)] lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)]">
        {/* LEFT — procedure and next action */}
        <div className="grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="Current Step"
            right={
              <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                {state.status}
              </span>
            }
          >
            {currentEngineStep ? (
              <>
                <p className="font-mono text-sm font-semibold">{currentEngineStep.label}</p>
                <p className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                  step {currentEngineStep.step_number}/{currentEngineStep.total_steps} ·{' '}
                  {currentEngineStep.activity}
                </p>
                {currentEngineStep.description && (
                  <p className="mt-1 font-mono text-[11px] text-on-surface-variant">
                    {currentEngineStep.description}
                  </p>
                )}
              </>
            ) : expected ? (
              <>
                <p className="font-mono text-sm font-semibold">{expected.label}</p>
                <p className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                  step {state.currentStepIndex + 1}/{state.experiment.steps.length} · {expected.activity}
                </p>
              </>
            ) : (
              <EmptyState
                compact
                icon="task_alt"
                title="Procedure complete"
                description="Every step in this protocol has been matched."
              />
            )}
          </Panel>

          <Panel title="Next Expected Action">
            {nextEngineStep ? (
              <>
                <p className="font-mono text-sm font-semibold">{nextEngineStep.label}</p>
                <p className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                  step {nextEngineStep.step_number} · {nextEngineStep.activity}
                </p>
              </>
            ) : expected ? (
              <KeyValue
                label={expected.object?.replace(/_/g, ' ') ?? 'action'}
                value={ACTION_LABEL[expected.action ?? ''] ?? (expected.action ?? 'observe')}
                color="var(--color-primary)"
              />
            ) : (
              <Empty label="No next action — the procedure has ended." />
            )}
          </Panel>

          <Panel title="Mission Procedure" scroll className="min-h-0">
            {state.experiment.steps.length === 0 ? (
              <EmptyState compact icon="science" title="No procedure loaded" />
            ) : (
              <ol className="rows">
                {state.experiment.steps.map((step, i) => {
                  const done = state.completedStepIds.includes(step.id)
                  const current = state.currentStepIndex === i
                  return (
                    <li
                      key={step.id}
                      className="flex items-center gap-2 border px-2 py-1.5"
                      style={{
                        borderColor: current
                          ? 'var(--color-primary)'
                          : done
                            ? 'color-mix(in oklab, var(--t-secondary) 50%, transparent)'
                            : 'color-mix(in oklab, var(--t-outline-variant) 40%, transparent)',
                        background: current
                          ? 'color-mix(in oklab, var(--t-primary) 10%, transparent)'
                          : done
                            ? 'color-mix(in oklab, var(--t-secondary) 8%, transparent)'
                            : 'var(--color-surface-container-low)',
                      }}
                    >
                      <span
                        className="flex h-4 w-4 shrink-0 items-center justify-center font-mono text-[9px] font-bold"
                        style={{
                          background: done
                            ? 'var(--color-secondary)'
                            : current
                              ? 'var(--color-primary)'
                              : 'transparent',
                          color: done || current ? 'var(--color-on-primary-container)' : 'var(--color-on-surface-variant)',
                          border: done || current ? undefined : '1px solid var(--t-outline-variant)',
                        }}
                      >
                        {done ? '✓' : i + 1}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-mono text-[11px] font-semibold">
                          {step.label}
                        </span>
                        <span className="block truncate font-mono text-[9px] uppercase tracking-widest text-on-surface-variant">
                          {ACTION_LABEL[step.action ?? ''] ?? step.action} · {step.activity}
                        </span>
                      </span>
                    </li>
                  )
                })}
              </ol>
            )}
          </Panel>
        </div>

        {/* CENTER — the camera, then live observation */}
        <Panel
          title="Live Observation"
          fill
          scroll={false}
          className="min-h-0"
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              CAM-01 · {phase === 'live' ? 'live' : phase} · {detections.length + unknownDetections.length}{' '}
              objects
            </span>
          }
        >
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex min-h-0 flex-1">
              <CameraStage
                detections={detections}
                unknownDetections={unknownDetections}
                frameWidth={frameW}
                frameHeight={frameH}
                hazardLevels={hazardLevels}
                unattendedIds={unattendedIds}
                fill
                aspect={frameW && frameH ? `${frameW} / ${frameH}` : '16 / 9'}
              />
            </div>
            <div className="mt-[var(--grid-gap)] grid shrink-0 grid-cols-1 gap-[var(--grid-gap)] sm:grid-cols-3">
              <SubCard
                title="Current activity"
                right={
                  observed ? (
                    <Badge color={observed.confidence >= 0.5 ? '#22c55e' : '#facc15'}>
                      {riskPercent(observed.confidence)}
                    </Badge>
                  ) : null
                }
              >
                {observed?.activity ? (
                  <p className="truncate font-mono text-[11px] font-semibold uppercase tracking-wider">
                    {observed.activity.replace(/_/g, ' ')}
                  </p>
                ) : (
                  <p className="font-mono text-[10px] text-on-surface-variant">
                    No activity interpretation for the current frame.
                  </p>
                )}
              </SubCard>

              <SubCard
                title="Human–object interaction"
                right={
                  <span className="font-mono text-[10px] text-on-surface-variant">
                    {attendance.status?.objects ?? 0} tracks
                  </span>
                }
              >
                {heldWatches.length > 0 ? (
                  <ul className="rows">
                    {heldWatches.slice(0, 3).map(w => (
                      <li key={w.instanceId} className="truncate font-mono text-[10px]">
                        <span className="font-semibold uppercase tracking-wider">
                          {w.className.replace(/_/g, ' ')}
                        </span>{' '}
                        <span className="text-on-surface-variant">
                          {w.personId ? `near ${w.personId}` : 'no crew associated'}
                          {w.personFreeMs > 0 ? ` · free ${Math.round(w.personFreeMs)}ms` : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="font-mono text-[10px] text-on-surface-variant">
                    No object is currently associated with a crew member.
                  </p>
                )}
              </SubCard>

              <SubCard
                title="Procedure intelligence"
                right={
                  classification?.result ? (
                    <Badge color={classificationResultColor(classification.result)}>
                      {classification.result.replace(/_/g, ' ')}
                    </Badge>
                  ) : null
                }
              >
                {classification ? (
                  <>
                    <p className="truncate font-mono text-[10px] text-on-surface">
                      {classification.message}
                    </p>
                    <p className="mt-0.5 truncate font-mono text-[9px] uppercase tracking-widest text-on-surface-variant">
                      expected {classification.expected ?? '—'} · observed {classification.activity ?? '—'}
                    </p>
                  </>
                ) : (
                  <p className="font-mono text-[10px] text-on-surface-variant">
                    No step has been classified yet.
                  </p>
                )}
                <div className="mt-1 grid grid-cols-4 gap-1">
                  <StatTile label="OOS" value={String(state.errors.outOfSequence)} />
                  <StatTile label="Skip" value={String(state.errors.skipped)} />
                  <StatTile label="Rep" value={String(state.errors.repeated)} />
                  <StatTile label="Unk" value={String(state.errors.unknown)} />
                </div>
              </SubCard>
            </div>
          </div>
        </Panel>

        {/* RIGHT — crew, reasoning, alerts, risk */}
        {/* All `auto` rows: an alert feed that is empty (or has one entry)
            must not become a several-hundred-pixel void. The list below is
            height-capped and scrolls internally instead. */}
        <div className="grid min-h-0 grid-rows-[auto_auto_auto_auto] gap-[var(--grid-gap)]">
          <Panel title="Astronaut Status">
            {snapshot?.astronaut_in_view ? (
              <>
                <div className="mb-1.5 grid grid-cols-2 gap-[var(--row-pad)]">
                  <StatTile
                    label="Confidence"
                    value={riskPercent(snapshot.astronaut_box?.confidence ?? 0)}
                    color={MISSION_COLORS.NORMAL}
                  />
                  <StatTile label="Box" value={astronautBoxLabel(snapshot.astronaut_box)} />
                </div>
                <KeyValue
                  label="Emergency"
                  value={emergency?.event_type.replace(/_/g, ' ') ?? 'none'}
                  color={emergency ? ALERT_COLORS.EMERGENCY : undefined}
                />
              </>
            ) : (
              <EmptyState
                compact
                icon="person_off"
                title="No crew in view"
                description={
                  stale
                    ? 'Feed is stale — the last known scene is retained and nothing new is claimed.'
                    : 'The detector has not reported a person in the current frame.'
                }
              />
            )}
          </Panel>

          <Panel
            title="ASTRA Reasoning"
            right={
              <Badge color={stateTone} pulse={monitorState !== 'NORMAL'}>
                {monitorState}
              </Badge>
            }
          >
            {topHazard ? (
              <>
                <p className="font-mono text-[11px] text-on-surface">{topHazard.reason}</p>
                {topHazard.recommended_action && (
                  <p
                    className="mt-1 font-mono text-[11px] font-semibold"
                    style={{ color: RISK_COLORS[topHazard.risk_level] }}
                  >
                    Action: {topHazard.recommended_action}
                  </p>
                )}
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <Badge color={topHazard.confirmed ? '#22c55e' : '#facc15'}>
                    {topHazard.confirmed ? 'Confirmed' : 'Candidate'}
                  </Badge>
                  <Badge color={topHazard.near_astronaut ? '#f97316' : '#64748b'}>
                    {topHazard.proximity === 'UNKNOWN_ASTRONAUT'
                      ? 'Proximity: no crew'
                      : `Proximity: ${topHazard.proximity.toLowerCase()}`}
                  </Badge>
                  <Badge color="#64748b">{topHazard.frames_persisted} frames</Badge>
                </div>
              </>
            ) : (
              <EmptyState
                compact
                icon="psychology"
                title="No hazard reasoning"
                description="ASTRA has no object to reason about in the current frame."
              />
            )}
          </Panel>

          <Panel
            title="Active Alerts"
            scroll
            className="min-h-0"
            right={
              <span className="font-mono text-xs font-bold" style={{ color: activeAlerts.length ? '#ef4444' : undefined }}>
                {activeAlerts.length}
                {acknowledgedAlerts.length > 0 && (
                  <span className="text-on-surface-variant"> / {acknowledgedAlerts.length} ack</span>
                )}
              </span>
            }
          >
            {safety.alerts.filter(a => !a.resolved).length === 0 ? (
              <EmptyState compact icon="notifications_off" title="No active alerts" />
            ) : (
              <ul className="rows max-h-40 overflow-y-auto">
                {safety.alerts
                  .filter(a => !a.resolved)
                  .map(a => (
                    <li
                      key={a.id}
                      className="flex items-center justify-between gap-2 border px-2 py-1"
                      style={{
                        borderLeftWidth: 3,
                        borderLeftColor: ALERT_COLORS[a.level],
                      }}
                    >
                      <span className="min-w-0 truncate font-mono text-[11px] font-bold uppercase tracking-wider">
                        {a.object ?? a.event_type.replace(/_/g, ' ')}
                      </span>
                      <Badge color={ALERT_COLORS[a.level]}>
                        {a.acknowledged ? 'ack' : a.level}
                      </Badge>
                    </li>
                  ))}
              </ul>
            )}
          </Panel>

          <Panel title="Risk & Monitor">
            <div className="grid grid-cols-2 gap-[var(--row-pad)]">
              <StatTile
                label="Risk"
                value={snapshot?.overall_risk_level ?? '—'}
                color={riskColor}
              />
              <StatTile
                label="Score"
                value={riskPercent(snapshot?.overall_risk_score ?? 0)}
                color={riskColor}
              />
              <StatTile label="Objects" value={String(snapshot?.assessments?.length ?? 0)} />
              <StatTile
                label="Unclassified"
                value={String(snapshot?.unclassified?.length ?? 0)}
                color={(snapshot?.unclassified?.length ?? 0) > 0 ? '#f97316' : undefined}
              />
            </div>
            <div className="mt-1.5">
              <KeyValue
                label="State"
                value={snapshot?.monitor.state ?? '—'}
                color={stateColor(monitorState)}
              />
              <KeyValue
                label="Since"
                value={
                  snapshot?.monitor.activeSince
                    ? formatTimestamp(snapshot.monitor.activeSince)
                    : '—'
                }
              />
              <KeyValue label="Detector" value={snapshot?.detector ?? '—'} />
            </div>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={safety.start}
                disabled={snapshot?.monitoring || safety.busy}
                className="btn-primary px-2 py-1 text-[10px]"
              >
                Monitor on
              </button>
              <button
                type="button"
                onClick={safety.stop}
                disabled={!snapshot?.monitoring || safety.busy}
                className="btn-outline px-2 py-1 text-[10px]"
              >
                Monitor off
              </button>
            </div>
          </Panel>
        </div>
      </div>

      {/* ── Bottom strip: history, tracking, performance ──────────── */}
      {/* The leftover viewport height belongs here: three real, variable-content
          feeds that scroll internally. `page-fill` supplies the flex growth, so
          only a floor is set — a fixed height left a dead band underneath. */}
      <div
        className="page-fill grid-cols-1 md:grid-cols-2 xl:grid-cols-3"
        style={{ minHeight: 'var(--strip-h)' }}
      >
        <Panel
          title="Event Timeline"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {safetyTimeline.length} events
            </span>
          }
        >
          <Timeline
            entries={safetyTimeline}
            empty={
              <EmptyState
                compact
                icon="history"
                title="No safety events yet"
                description="The safety engine has not logged a transition."
                lastUpdated={
                  snapshot?.timestamp ? formatTimestamp(snapshot.timestamp) : undefined
                }
              />
            }
          />
        </Panel>

        <Panel
          title="Object Tracking"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {attendance.status?.objects ?? 0} tracked
            </span>
          }
        >
          <div className="stack">
            <div className="grid grid-cols-4 gap-[var(--row-pad)]">
              <StatTile label="Tracked" value={String(attendance.status?.objects ?? 0)} />
              <StatTile
                label="Held"
                value={String(attendance.status?.heldCount ?? 0)}
                color={(attendance.status?.heldCount ?? 0) > 0 ? '#facc15' : undefined}
              />
              <StatTile label="In box" value={String(attendance.status?.inContainerCount ?? 0)} />
              <StatTile
                label="Unattended"
                value={String(attendance.status?.unattendedCount ?? 0)}
                color={(attendance.status?.unattendedCount ?? 0) > 0 ? '#ef4444' : undefined}
              />
            </div>
            <Timeline
              entries={attendanceTimeline}
              empty={
                <EmptyState
                  compact
                  icon="inventory_2"
                  title="No tracked objects"
                  description="Attendance starts tracking when an object appears near a person or a container."
                />
              }
            />
          </div>
        </Panel>

        <Panel
          title="AI Performance"
          fill
          scroll
          right={<InlineStatus value={detection.result?.inferenceStatus ?? '—'} />}
        >
          <div className="grid grid-cols-2 gap-[var(--row-pad)] sm:grid-cols-3">
            <StatTile label="Detector" value={detection.status?.detector ?? '—'} />
            <StatTile
              label="Inference"
              value={detection.result?.inferenceStatus ?? '—'}
              color={
                detection.result?.inferenceStatus === 'ok'
                  ? '#22c55e'
                  : detection.result?.inferenceStatus === 'error'
                    ? '#ef4444'
                    : undefined
              }
            />
            <StatTile
              label="Latency"
              value={
                detection.result?.inferenceMs != null ? `${detection.result.inferenceMs}ms` : '—'
              }
            />
            <StatTile
              label="AI rate"
              value={
                detection.status
                  ? `${detection.status.actualFps.toFixed(1)}/${detection.status.targetFps || '∞'} fps`
                  : '—'
              }
            />
            <StatTile
              label="Forwards"
              value={detection.status ? String(detection.status.inferenceCount) : '—'}
            />
            <StatTile
              label="Dropped"
              value={detection.status ? String(detection.status.skippedForRate) : '—'}
              title="Camera frames skipped because the AI rate gate was not due yet"
            />
            <StatTile label="Stable" value={String(detections.length)} />
            <StatTile
              label="Unknown"
              value={String(unknownDetections.length)}
              color={unknownDetections.length > 0 ? '#f97316' : undefined}
            />
            <StatTile label="Trace" value={detection.status?.traceEnabled ? 'on' : 'off'} />
          </div>
          {detection.result?.error && (
            <p className="mt-1.5 border border-error/40 bg-error/10 px-2 py-1 font-mono text-[10px] text-error">
              AI engine error: {detection.result.error}
            </p>
          )}
        </Panel>
      </div>
    </PageShell>
  )
}

function astronautBoxLabel(box: { x1: number; y1: number; x2: number; y2: number } | null | undefined): string {
  if (!box) return '—'
  return `${box.x2 - box.x1}×${box.y2 - box.y1}`
}

/** Accent for a state-machine classification, mirroring the backend palette. */
function classificationResultColor(result: string): string {
  switch (result) {
    case 'CORRECT':
      return '#22c55e'
    case 'OUT_OF_SEQUENCE':
    case 'SKIPPED':
      return '#f97316'
    case 'REPEATED':
      return '#facc15'
    default:
      return '#ef4444'
  }
}

/** Inline status word, kept as a component so the strip header stays compact. */
function InlineStatus({ value }: { value: string }) {
  const ok = value === 'ok'
  return (
    <span
      className="font-mono text-[10px] font-bold uppercase tracking-wider"
      style={{ color: ok ? '#22c55e' : value === 'error' ? '#ef4444' : 'var(--color-on-surface-variant)' }}
    >
      {value}
    </span>
  )
}

export function HazardCard({ assessment }: { assessment: HazardAssessment }) {
  const color = RISK_COLORS[assessment.risk_level] ?? '#64748b'
  return (
    <div
      className="border border-outline-variant/30 bg-surface-container-low p-2"
      style={{ borderLeftWidth: 3, borderLeftColor: color }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs font-bold uppercase tracking-wider">
            {assessment.object.replace(/_/g, ' ')}
          </p>
          <p className="truncate font-mono text-[10px] text-on-surface-variant">
            {assessment.hazard_type?.replace(/_/g, ' ') ?? 'unclassified'} · conf{' '}
            {riskPercent(assessment.confidence)}
          </p>
        </div>
        <Badge color={color} pulse={assessment.confirmed && assessment.risk_level !== 'SAFE'}>
          {assessment.risk_level} {riskPercent(assessment.risk_score)}
        </Badge>
      </div>

      <div className="mt-1.5 flex flex-wrap gap-1">
        <Badge color={assessment.confirmed ? '#22c55e' : '#facc15'}>
          {assessment.confirmed ? 'Confirmed' : 'Candidate'}
        </Badge>
        <Badge color={assessment.proximity === 'NEAR' ? '#f97316' : '#64748b'}>
          {assessment.proximity === 'UNKNOWN_ASTRONAUT'
            ? 'Proximity: no crew in view'
            : `Proximity: ${assessment.proximity.toLowerCase()}`}
        </Badge>
        {assessment.moving_toward_astronaut && <Badge color="#ef4444">Moving toward crew</Badge>}
        {assessment.unclassified && <Badge color="#a78bfa">Unclassified</Badge>}
        <Badge color="#64748b">{assessment.frames_persisted} frames</Badge>
      </div>

      <p className="mt-1.5 font-mono text-[10px] leading-snug text-on-surface-variant">
        {assessment.reason}
      </p>
      {assessment.recommended_action && (
        <p className="mt-1 font-mono text-[10px] font-semibold" style={{ color }}>
          Action: {assessment.recommended_action}
        </p>
      )}
    </div>
  )
}

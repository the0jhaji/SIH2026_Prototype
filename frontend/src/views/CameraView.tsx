import { useMemo } from 'react'
import { CAMERA_STREAM_URL } from '../domain/camera'
import {
  BOX_COLORS,
  CLASS_COLOR,
  UNKNOWN_CLASS,
  hazardLevelsFrom,
  unattendedIdsFrom,
  type Detection,
} from '../domain/detection'
import { expectedStep } from '../domain/experiment'
import { LiveCameraFeed } from '../components/LiveFeed'
import { EmptyState, KeyValue, Panel, StatTile } from './ui'
import { PageShell, Timeline } from './layout'
import { attendanceEventEntries, basEventEntries, relativeAge, safetyEventEntries, severityColor, stateColor } from './helpers'
import type { SafetyCommonProps } from './props'

/** Stage duration for the trace panel. `—` means the stage never ran, not 0 ms. */
function fmtMs(value: number | null | undefined): string {
  return value == null ? '—' : `${value.toFixed(1)}ms`
}

const STATE_TONE: Record<string, string> = {
  UNATTENDED: 'border-error/50 bg-error/10',
  RELEASED: 'border-warning/50 bg-warning/10',
  ATTENDED: 'border-outline-variant/40 bg-surface-container-low',
  OBJECT_INSIDE_BOX: 'border-primary/40 bg-primary/10',
}

function watchTone(state: string): string {
  return STATE_TONE[state] ?? 'border-outline-variant/40 bg-surface-container-low'
}

const ACTION_LABEL: Record<string, string> = { PICK: 'Pick', PLACE: 'Place', OPEN: 'Open' }

/** Row shares of the page height.
 *
 *  The video is height-bound, not width-bound: a 16:9 source in a panel this
 *  wide is always limited by the height it is given, so the only way to make
 *  the feed larger is to hand its row more of the page. The cards and the
 *  monitoring strip keep their own content and layout — they just take a
 *  smaller slice, and both scroll internally, so no region is left blank. */
const CAMERA_ROW = '1 1 74%'
const INTEL_ROW = '1 1 15%'
const MONITOR_ROW = '1 1 11%'

/**
 * LIVE OBSERVATION — the camera is the page.
 *
 * The live frame is the primary element: it fills a 16:9 box sized from the
 * camera's own resolution (never stretched, `object-contain` inside a box that
 * already matches the frame aspect), with the transport controls docked
 * directly beneath it. Everything else is intelligence *about* that frame —
 * what the crew member is doing, what they are holding, where the procedure
 * stands, and the raw telemetry — arranged so no region of the page is left
 * blank.
 *
 * The picture and its overlay come from the same `LiveCameraFeed` the rest of
 * the app uses, fed by `/api/camera/stream` and the backend's real
 * `frameWidth`/`frameHeight`, so YOLO boxes, labels, tracking ids, confidence
 * and the unknown/hazard/unattended markers land on the objects they describe.
 * Nothing here is simulated: with the camera stopped the panel says so instead
 * of inventing a frame.
 */
export function CameraView({
  state,
  engine,
  camera,
  cameraRunning,
  cameraOffline,
  onCameraStart,
  onCameraStop,
  safety,
  detection,
  attendance,
}: SafetyCommonProps) {
  const status = detection.status
  const result = detection.result
  const streamRunning = cameraRunning
  const detections = streamRunning ? (result?.detections ?? []) : []
  const unknownDetections = streamRunning ? (result?.unknownDetections ?? []) : []
  const frameW = streamRunning ? (result?.frameWidth ?? null) : null
  const frameH = streamRunning ? (result?.frameHeight ?? null) : null
  const hazardLevels = useMemo(() => hazardLevelsFrom(safety.snapshot?.assessments), [safety.snapshot])
  const unattendedIds = useMemo(() => unattendedIdsFrom(attendance.result?.watches), [attendance])
  const allDetections = [...detections, ...unknownDetections]
  const snapshot = safety.snapshot
  const tone = stateColor(snapshot?.mission_state)
  const activeAlerts = safety.alerts.filter(a => !a.resolved)

  const expected = expectedStep(state.experiment, state.currentStepIndex)
  const observed = state.currentDetected ?? null
  const activityLabel = observed?.activity
    ? observed.activity.replace(/_/g, ' ')
    : (engine?.last_activity?.label ?? null)
  const activityConfidence = observed?.confidence ?? engine?.last_activity?.confidence ?? null
  const activityTs = observed?.ts ?? null

  const watches = attendance.result?.watches ?? []
  const nearAstronaut = watches.filter(w => w.personId != null)
  const held = watches.find(w => w.state === 'HELD') ?? null
  const interactionState = held
    ? 'HELD'
    : (attendance.status?.unattendedCount ?? 0) > 0
      ? 'UNATTENDED'
      : nearAstronaut.length > 0
        ? 'IN CONTACT'
        : watches.length > 0
          ? 'TRACKING'
          : 'NO CONTACT'

  const activityTimeline = useMemo(() => basEventEntries(state.log, 40), [state.log])
  const systemTimeline = useMemo(
    () => [...safetyEventEntries(safety.events, 30), ...attendanceEventEntries(attendance.result?.events, 20)],
    [safety.events, attendance.result?.events],
  )

  return (
    <PageShell>
      {/* ── 1. Live camera — the primary element ─────────────────────── */}
      <div className="min-h-[15rem]" style={{ flex: CAMERA_ROW }}>
        <Panel
          title="Live Camera Feed"
          fill
          scroll={false}
          accent={snapshot?.top_hazard ? BOX_COLORS.hazard : undefined}
          right={
            <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
              CAM-01 · {streamRunning ? 'LIVE' : 'STANDBY'} · {detections.length + unknownDetections.length}{' '}
              OBJECTS
            </span>
          }
        >
          {streamRunning ? (
            /* No height floor here: the row is flex-sized and the box takes all
               of it, so the feed claims every pixel the panel can give it. */
            <div className="flex min-h-0 flex-1 items-center justify-center">
              <div className="flex h-full w-full flex-col">
                <div className="relative flex min-h-0 flex-1 flex-col">
                  <LiveCameraFeed
                    streamUrl={CAMERA_STREAM_URL}
                    detections={detections}
                    unknownDetections={unknownDetections}
                    frameWidth={frameW}
                    frameHeight={frameH}
                    hazardLevels={hazardLevels}
                    unattendedIds={unattendedIds}
                    fill
                    fit="cover"
                  />

                  {/* Real telemetry only — every field is a live backend value. */}
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 px-2 pb-1 font-mono text-[10px] uppercase tracking-wider text-slate-300">
                    <span className="flex gap-3">
                      <span style={{ color: status?.enabled ? '#4ade80' : '#f97316' }}>
                        INF {status?.enabled ? 'ONLINE' : 'OFFLINE'}
                      </span>
                      <span>FPS {status ? status.actualFps.toFixed(1) : '—'}</span>
                      <span>LAT {result?.inferenceMs != null ? `${result.inferenceMs}ms` : '—'}</span>
                      <span>TRK {attendance.status?.objects ?? 0}</span>
                    </span>
                    <span>
                      {frameW && frameH ? `${frameW}×${frameH}` : '—'} · {status?.detector ?? '—'}
                    </span>
                  </div>
                </div>

                {/* Transport controls, docked directly under the frame and
                    sharing its width. */}
                <div className="grid shrink-0 grid-cols-2 gap-2 pt-2">
                  <button
                    type="button"
                    onClick={onCameraStart}
                    disabled={cameraRunning || cameraOffline}
                    className="btn-primary"
                  >
                    <span className="msym text-base leading-none">videocam</span>
                    CAM ON
                  </button>
                  <button
                    type="button"
                    onClick={onCameraStop}
                    disabled={!cameraRunning}
                    className="btn-outline"
                  >
                    <span className="msym text-base leading-none">videocam_off</span>
                    CAM OFF
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex min-h-[12rem] flex-1 items-center justify-center bg-black">
              <EmptyState
                icon="videocam_off"
                title={cameraOffline ? 'Camera offline' : 'Camera stopped'}
                description={
                  cameraOffline
                    ? 'The backend is not reachable, so no camera control is available.'
                    : 'Press CAM ON to start visual monitoring. Nothing is inferred without a live frame.'
                }
                status={camera ? `${camera.width}×${camera.height} · ${camera.fps}fps configured` : undefined}
                lastUpdated={camera ? 'no frames are being served' : undefined}
              />
            </div>
          )}
        </Panel>
      </div>

      {/* ── 2. Intelligence about the frame ──────────────────────────── */}
      <div
        className="grid min-h-0 grid-cols-1 gap-[var(--grid-gap)] lg:grid-cols-3"
        style={{ flex: INTEL_ROW }}
      >
        <Panel title="Current Activity" fill scroll>
          <KeyValue label="Detected activity" value={activityLabel ?? '—'} color={activityLabel ? '#4cd7f6' : undefined} />
          <KeyValue
            label="Confidence"
            value={activityConfidence != null ? `${Math.round(activityConfidence * 100)}%` : '—'}
          />
          <KeyValue label="Activity state" value={state.status} color={tone} />
          <KeyValue
            label="Last result"
            value={state.lastClassification?.result ?? '—'}
            color={state.lastClassification ? severityColor(state.lastClassification.severity) : undefined}
          />
          <KeyValue
            label="Detection time"
            value={activityTs ? `${new Date(activityTs).toLocaleTimeString()} (${relativeAge(activityTs)})` : '—'}
          />
        </Panel>

        <Panel title="Human–Object Interaction" fill scroll>
          <KeyValue label="Tracked objects" value={String(attendance.status?.objects ?? 0)} />
          <KeyValue
            label="Near astronaut"
            value={String(nearAstronaut.length)}
            color={nearAstronaut.length > 0 ? '#4cd7f6' : undefined}
          />
          <KeyValue
            label="Currently held"
            value={held ? held.className.replace(/_/g, ' ') : 'none'}
            color={held ? '#4ade80' : undefined}
          />
          <KeyValue
            label="Interaction state"
            value={interactionState}
            color={
              interactionState === 'HELD'
                ? '#4ade80'
                : interactionState === 'UNATTENDED'
                  ? '#ef4444'
                  : undefined
            }
          />
          <KeyValue
            label="Unattended"
            value={String(attendance.status?.unattendedCount ?? 0)}
            color={(attendance.status?.unattendedCount ?? 0) > 0 ? '#ef4444' : undefined}
          />
          <KeyValue label="In container" value={String(attendance.status?.inContainerCount ?? 0)} />
          {attendance.status && (
            <p className="mt-1.5 font-mono text-[10px] leading-snug text-on-surface-variant">
              proximity ≤ {attendance.status.thresholds.proximity} · containment ≥{' '}
              {attendance.status.thresholds.containment} · arm reach{' '}
              {attendance.status.thresholds.armReach} · held {attendance.status.thresholds.heldFrames}{' '}
              frames · tracked {attendance.status.thresholds.trackedClasses.length} classes ·{' '}
              {attendance.status.monitoring ? 'monitoring on' : 'monitoring off'}
            </p>
          )}
          {watches.length > 0 ? (
            <ul className="rows mt-1.5">
              {watches.map(w => (
                <li key={w.instanceId} className={`border px-2 py-1 ${watchTone(w.state)}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-[11px] font-bold uppercase tracking-wider">
                      {w.className.replace(/_/g, ' ')}
                    </span>
                    <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider">
                      {w.state.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[10px] opacity-80">
                    <span>id {w.instanceId}</span>
                    {w.insideContainer && (
                      <span>
                        in {w.containerClass?.replace(/_/g, ' ') ?? '?'} ·{' '}
                        {(w.containmentScore * 100).toFixed(0)}%
                      </span>
                    )}
                    {w.personId && <span>held by {w.personId}</span>}
                    {w.isUnknown && <span>unknown class</span>}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 font-mono text-[10px] text-on-surface-variant">
              {streamRunning ? 'Tracking objects. Show an object near the astronaut.' : 'Camera offline — no interaction data.'}
            </p>
          )}
        </Panel>

        <Panel title="Procedure Intelligence" fill scroll>
          <KeyValue
            label="Current step"
            value={
              expected
                ? `${state.currentStepIndex + 1}/${state.experiment.steps.length} · ${expected.label}`
                : 'Procedure complete'
            }
          />
          <KeyValue
            label="Expected action"
            value={expected ? `${ACTION_LABEL[expected.action ?? ''] ?? expected.action} ${expected.object ?? ''}`.trim() : '—'}
            color="#4cd7f6"
          />
          <KeyValue
            label="Observed action"
            value={activityLabel ?? '—'}
            color={
              state.lastClassification?.result === 'CORRECT'
                ? '#4ade80'
                : state.lastClassification?.result
                  ? '#f97316'
                  : undefined
            }
          />
          <KeyValue label="Procedure status" value={state.status} color={tone} />
          <KeyValue
            label="Confidence"
            value={activityConfidence != null ? `${Math.round(activityConfidence * 100)}%` : '—'}
          />
          <div className="mt-1.5 grid grid-cols-4 gap-[var(--row-pad)]">
            <StatTile label="OOS" value={String(state.errors.outOfSequence)} color={state.errors.outOfSequence > 0 ? '#f97316' : undefined} />
            <StatTile label="SKIP" value={String(state.errors.skipped)} color={state.errors.skipped > 0 ? '#f97316' : undefined} />
            <StatTile label="REP" value={String(state.errors.repeated)} color={state.errors.repeated > 0 ? '#f97316' : undefined} />
            <StatTile label="UNK" value={String(state.errors.unknown)} color={state.errors.unknown > 0 ? '#ef4444' : undefined} />
          </div>
          {engine && (
            <p className="mt-1.5 font-mono text-[10px] text-on-surface-variant">
              engine {engine.status} · {engine.completed_count}/{engine.total_steps} complete ·{' '}
              {engine.violation_count} violation{engine.violation_count === 1 ? '' : 's'}
            </p>
          )}
          <ol className="rows mt-1.5">
            {state.experiment.steps.map((step, i) => {
              const done = state.completedStepIds.includes(step.id)
              const current = state.status === 'RUNNING' && expected?.id === step.id
              return (
                <li
                  key={step.id}
                  className="flex items-center gap-2 border px-2 py-1"
                  style={{
                    borderColor: done
                      ? 'color-mix(in oklab, #22c55e 45%, transparent)'
                      : current
                        ? 'color-mix(in oklab, var(--color-primary) 60%, transparent)'
                        : 'color-mix(in oklab, var(--t-outline-variant) 30%, transparent)',
                  }}
                >
                  <span className="shrink-0 font-mono text-[10px] font-bold">{done ? '✓' : i + 1}</span>
                  <span className="min-w-0 flex-1 truncate font-mono text-[10px]">{step.label}</span>
                  <span className="shrink-0 font-mono text-[9px] uppercase tracking-wider text-on-surface-variant">
                    {ACTION_LABEL[step.action ?? ''] ?? step.action}
                  </span>
                </li>
              )
            })}
          </ol>
        </Panel>
      </div>

      {/* ── 3. Compact AI monitoring strip ───────────────────────────── */}
      <div
        className="grid min-h-0 grid-cols-1 gap-[var(--grid-gap)] md:grid-cols-2 xl:grid-cols-4"
        style={{ flex: MONITOR_ROW }}
      >
        <Panel
          title="Activity Timeline"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {activityTimeline.length}
            </span>
          }
        >
          {activityTimeline.length === 0 ? (
            <EmptyState compact icon="history" title="No activity events" />
          ) : (
            <Timeline entries={activityTimeline} />
          )}
        </Panel>

        <Panel
          title="Object Tracking"
          fill
          scroll
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              {allDetections.length} in frame
            </span>
          }
        >
          {allDetections.length === 0 ? (
            <EmptyState
              compact
              icon="search_off"
              title={streamRunning ? 'No objects in frame' : 'Camera offline'}
              description={
                streamRunning
                  ? 'The detector is running but has not recognised anything in the current frame.'
                  : 'Nothing to interpret without the live feed.'
              }
            />
          ) : (
            <ul className="rows">
              {allDetections.map((d, i) => (
                <DetectionRow
                  key={`${d.instance_id ?? d.timestamp}-${i}`}
                  detection={d}
                  unattended={unattendedIds.has(d.instance_id ?? '')}
                />
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="AI Inference Status" fill scroll>
          {status ? (
            <>
              <div className="tile-grid grid-cols-2">
                <StatTile label="Detector" value={status.detector ?? '—'} />
                <StatTile
                  label="Inference"
                  value={result?.inferenceStatus ?? (status.enabled ? 'ONLINE' : 'OFFLINE')}
                  color={status.enabled ? '#4ade80' : '#f97316'}
                />
                <StatTile
                  label="Latency"
                  value={result?.inferenceMs != null ? `${result.inferenceMs}ms` : '—'}
                />
                <StatTile label="FPS" value={status.actualFps.toFixed(1)} />
                <StatTile
                  label="Frame"
                  value={result?.frameWidth ? `${result.frameWidth}x${result.frameHeight}` : '—'}
                />
                <StatTile label="Dropped" value={String(status.skippedForRate)} />
                <StatTile
                  label="Raw/Stable"
                  value={`${status.rawDetectionCount}/${status.detectionCount}`}
                  title="Current-frame detections / temporally stabilised detections"
                />
                <StatTile
                  label="AI rate"
                  value={`${status.actualFps.toFixed(1)}/${status.targetFps || '∞'}`}
                  title="Measured AI inferences per second / configured cap"
                />
                <StatTile
                  label="Last infer"
                  value={status.lastInference ? relativeAge(status.lastInference) : '—'}
                />
                <StatTile
                  label="Trace"
                  value={status.traceEnabled ? (status.traceLevel ?? status.trace?.level ?? 'on') : 'OFF'}
                />
              </div>
              {status.error && (
                <p className="mt-1.5 border border-error/40 bg-error/10 px-2 py-1 font-mono text-[10px] text-error">
                  AI ENGINE ERROR: {status.error}
                </p>
              )}
              <p className="mt-1.5 break-all font-mono text-[10px] text-on-surface-variant">
                {status.modelPath ?? 'no model loaded'}
              </p>
              {status.generalPurpose === false && (
                <p className="mt-1.5 border border-warning/50 bg-warning/10 px-2 py-1 font-mono text-[10px] text-warning">
                  SPECIALISED MODEL — {status.classCount} classes only. It CANNOT detect
                  person/bottle/cup/laptop. Set DETECTION_BACKEND=yolo for the general model.
                </p>
              )}
              <div className="tile-grid mt-1.5 grid-cols-3">
                <StatTile label="Classes" value={String(status.classCount ?? '—')} />
                <StatTile label="Size" value={status.modelSizeMb != null ? `${status.modelSizeMb}MB` : '—'} />
                <StatTile label="imgsz" value={String(status.inputSize ?? '—')} />
                <StatTile label="conf" value={String(status.confThreshold ?? '—')} />
                <StatTile label="iou" value={String(status.iouThreshold ?? '—')} />
                <StatTile
                  label="Role"
                  value={
                    status.generalPurpose === false ? 'SPECIAL' : status.generalPurpose ? 'GENERAL' : '—'
                  }
                />
              </div>
              {status.classes ? (
                <ul className="mt-1.5 flex flex-wrap gap-1">
                  {status.classes.map(c => (
                    <li
                      key={c}
                      className="border border-outline-variant/40 bg-surface-container-low px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-on-surface-variant"
                    >
                      {c.replace(/_/g, ' ')}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1.5 font-mono text-[10px] text-on-surface-variant">
                  No class vocabulary (generic model).
                </p>
              )}
              {status.traceEnabled && status.trace && (
                <>
                  <div className="tile-grid mt-1.5 grid-cols-3">
                    <StatTile label="Level" value={status.traceLevel ?? status.trace.level} />
                    <StatTile label="Events" value={String(status.trace.eventsTotal)} />
                    <StatTile label="Rate" value={`${status.trace.eventsPerSecond.toFixed(1)}/s`} />
                    <StatTile label="capture" value={fmtMs(status.trace.captureMs)} />
                    <StatTile label="yolo" value={fmtMs(status.trace.yoloMs)} />
                    <StatTile label="unknown" value={fmtMs(status.trace.unknownDetectorMs)} />
                    <StatTile label="tracker" value={fmtMs(status.trace.trackerMs)} />
                    <StatTile label="openclip" value={fmtMs(status.trace.openclipMs)} />
                    <StatTile label="hazard" value={fmtMs(status.trace.hazardMs)} />
                  </div>
                  {status.trace.errors > 0 && (
                    <p className="mt-1.5 border border-error/40 bg-error/10 px-2 py-1 font-mono text-[10px] text-error">
                      TRACER ERROR: {status.trace.errors} failure(s) — diagnostics are incomplete
                    </p>
                  )}
                </>
              )}
            </>
          ) : (
            <EmptyState
              compact
              icon="memory"
              title="Detection engine offline"
              description="No status payload from /api/detection/status."
            />
          )}
        </Panel>

        <Panel
          title="System Events"
          fill
          scroll
          right={
            <span
              className="font-mono text-[10px] font-bold uppercase tracking-wider"
              style={{ color: activeAlerts.length > 0 ? '#ef4444' : tone }}
            >
              {activeAlerts.length} alert{activeAlerts.length === 1 ? '' : 's'}
            </span>
          }
        >
          <div className="tile-grid mb-[var(--row-pad)] grid-cols-2">
            <StatTile label="Mission" value={snapshot?.mission_state ?? (safety.offline ? 'offline' : '—')} color={tone} />
            <StatTile
              label="Risk"
              value={snapshot?.overall_risk_level ?? '—'}
              color={snapshot ? tone : undefined}
            />
            <StatTile
              label="Risk score"
              value={snapshot ? `${Math.round(snapshot.overall_risk_score * 100)}%` : '—'}
            />
            <StatTile
              label="Top hazard"
              value={snapshot?.top_hazard?.object ?? 'none'}
              color={snapshot?.top_hazard ? BOX_COLORS.hazard : undefined}
            />
            <StatTile
              label="Feed"
              value={snapshot?.feed_stale ? 'stale' : streamRunning ? 'fresh' : '—'}
              color={snapshot?.feed_stale ? '#f97316' : streamRunning ? '#4ade80' : undefined}
            />
            <StatTile label="Monitoring" value={snapshot?.monitoring ? 'ON' : 'OFF'} />
          </div>
          {activeAlerts.length > 0 && (
            <ul className="rows">
              {activeAlerts.slice(0, 3).map(a => (
                <li
                  key={a.id}
                  className="truncate font-mono text-[10px] font-bold uppercase tracking-wider"
                  style={{ color: BOX_COLORS.hazard }}
                >
                  {a.level} — {a.title}
                </li>
              ))}
            </ul>
          )}
          {systemTimeline.length === 0 ? (
            <EmptyState compact icon="history" title="No system events yet" />
          ) : (
            <Timeline entries={systemTimeline} />
          )}
        </Panel>
      </div>
    </PageShell>
  )
}

/** One detection: class, confidence and the backend tracking id. */
function DetectionRow({ detection: d, unattended }: { detection: Detection; unattended: boolean }) {
  const isUnknown = d.class_name === UNKNOWN_CLASS
  return (
    <li
      className="border px-2 py-1"
      style={{
        borderLeftWidth: 3,
        borderLeftColor: unattended
          ? BOX_COLORS.unattended
          : isUnknown
            ? BOX_COLORS.unknown
            : (CLASS_COLOR[d.class_name] ?? '#4cd7f6'),
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate font-mono text-[11px] font-bold uppercase tracking-wider">
          {unattended ? 'unattended object' : isUnknown ? '? unknown object' : d.class_name.replace(/_/g, ' ')}
        </span>
        <span className="shrink-0 font-mono text-[11px] text-secondary">
          {Math.round(d.confidence * 100)}%
        </span>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[10px] text-on-surface-variant">
        <span>id: {d.instance_id ?? '—'}</span>
        {unattended && <span className="text-error">UNATTENDED</span>}
        {isUnknown && <span>unknown class</span>}
      </div>
    </li>
  )
}

import { useMemo } from 'react'
import { CAMERA_PHASE_COLOR, CAMERA_PHASE_LABEL } from '../domain/camera'
import {
  BOX_COLORS,
  CLASS_COLOR,
  UNKNOWN_CLASS,
  hazardLevelsFrom,
  unattendedIdsFrom,
  type Detection,
} from '../domain/detection'
import { CameraControls } from '../components/CameraControls'
import { CameraViewport } from '../components/CameraStage'
import { EmptyState, Panel, StatTile } from './ui'
import { PageShell, Timeline } from './layout'
import { attendanceEventEntries, basEventEntries, relativeAge, safetyEventEntries, stateColor } from './helpers'
import { useCamera } from '../hooks/cameraController'
import type { SafetyCommonProps } from './props'

/** Stage duration for the trace panel. `—` means the stage never ran, not 0 ms. */
function fmtMs(value: number | null | undefined): string {
  return value == null ? '—' : `${value.toFixed(1)}ms`
}

/** Row shares of the page height.
 *
 *  The camera row is content-sized (`0 0 auto`): its viewport is a 16:9 box
 *  sized from the available width, so squeezing the row would distort that box
 *  and force `cover` to crop. When the two rows together are taller than the
 *  viewport, `.page-scroll` scrolls — it is this view's designated scrolling
 *  region — instead of the frame being squashed. The monitoring strip keeps the
 *  share it already had. */
const CAMERA_ROW = '0 0 auto'
const MONITOR_ROW = '0 0 11%'

/**
 * LIVE OBSERVATION — the camera is the page.
 *
 * The live frame is the only thing in the main content area: it fills it edge
 * to edge, with the transport controls docked directly beneath it. Current
 * Activity, Human-Object Interaction and Procedure Intelligence are no longer
 * rendered here — that telemetry is unchanged and still served by the
 * monitoring strip below and by the Mission, Experiments, Station and Alerts
 * views; only this panel's copy of it is gone.
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
  safety,
  detection,
  attendance,
}: SafetyCommonProps) {
  // The one canonical camera state. This view holds no camera booleans of its
  // own, so it cannot disagree with any other page.
  const { phase, streamActive } = useCamera()
  const status = detection.status
  const result = detection.result
  const detections = streamActive ? (result?.detections ?? []) : []
  const unknownDetections = streamActive ? (result?.unknownDetections ?? []) : []
  const frameW = streamActive ? (result?.frameWidth ?? null) : null
  const frameH = streamActive ? (result?.frameHeight ?? null) : null

  // The AI engine reports itself. A detector error is an AI fact and must not
  // propagate into the camera's phase.
  const aiLabel = detection.offline
    ? 'UNREACHABLE'
    : status?.inferenceStatus === 'error'
      ? 'ERROR'
      : status?.enabled
        ? 'RUNNING'
        : 'IDLE'
  const aiColor = detection.offline || status?.inferenceStatus === 'error' ? '#f87171' : status?.enabled ? '#4ade80' : '#94a3b8'
  const hazardLevels = useMemo(() => hazardLevelsFrom(safety.snapshot?.assessments), [safety.snapshot])
  const unattendedIds = useMemo(() => unattendedIdsFrom(attendance.result?.watches), [attendance])
  const allDetections = [...detections, ...unknownDetections]
  const snapshot = safety.snapshot
  const tone = stateColor(snapshot?.mission_state)
  const activeAlerts = safety.alerts.filter(a => !a.resolved)

  const activityTimeline = useMemo(() => basEventEntries(state.log, 40), [state.log])
  const systemTimeline = useMemo(
    () => [...safetyEventEntries(safety.events, 30), ...attendanceEventEntries(attendance.result?.events, 20)],
    [safety.events, attendance.result?.events],
  )

  return (
    <PageShell>
      {/* ── 1. Live camera — the primary element ─────────────────────── */}
      <div style={{ flex: CAMERA_ROW }}>
        <Panel
          title="Live Camera Feed"
          fill
          scroll={false}
          accent={snapshot?.top_hazard ? BOX_COLORS.hazard : undefined}
          right={
            <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
              CAM-01 · {CAMERA_PHASE_LABEL[phase]} · {detections.length + unknownDetections.length}{' '}
              OBJECTS
            </span>
          }
        >
          {/*
            The viewport and the transport are SIBLINGS and neither is inside a
            `cameraRunning` branch. They used to live inside it, which meant that
            stopping the camera removed the CAM ON button along with the video and
            left this page — the one place you go to start the camera — with no way
            to start it. The controls cannot be lost now: nothing below depends on
            whether a frame exists.
          */}
          <div className="flex w-full flex-col">
            <CameraViewport
              detections={detections}
              unknownDetections={unknownDetections}
              frameWidth={frameW}
              frameHeight={frameH}
              hazardLevels={hazardLevels}
              unattendedIds={unattendedIds}
              fill
              aspect={frameW && frameH ? `${frameW} / ${frameH}` : '16 / 9'}
            />
            <CameraControls className="mt-2" />

            {/* Telemetry is a sibling of the viewport, not an overlay inside it,
                so it can never influence the video's box — and it renders even
                with no feed, showing `—` rather than disappearing. The camera
                line and the AI line are deliberately separate: YOLO failing must
                not change what the camera says about itself. */}
            <div className="mt-1.5 flex shrink-0 items-center justify-between gap-2 font-mono text-[10px] uppercase tracking-wider text-slate-400">
              <span className="flex gap-3">
                <span style={{ color: CAMERA_PHASE_COLOR[phase] }}>CAM {CAMERA_PHASE_LABEL[phase]}</span>
                <span style={{ color: aiColor }}>
                  AI {aiLabel}
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
        </Panel>
      </div>


      {/* ── 2. Compact AI monitoring strip ───────────────────────────── */}
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
              title={streamActive ? 'No objects in frame' : 'No camera feed'}
              description={
                streamActive
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
              value={phase === 'stale' ? 'stale' : streamActive ? 'fresh' : '—'}
              color={phase === 'stale' ? '#fbbf24' : streamActive ? '#4ade80' : undefined}
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

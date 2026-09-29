import { useMemo } from 'react'
import { expectedStep } from '../domain/experiment'
import { MISSION_COLORS } from '../domain/safety'
import { LiveFeed } from '../components/LiveFeed'
import { CameraStage } from '../components/CameraStage'
import { useCamera } from '../hooks/cameraController'
import { hazardLevelsFrom, resolveFrameSize, unattendedIdsFrom } from '../domain/detection'
import { VOICE_READY, voiceState, voiceStateDetail, voiceStateLabel, voiceStateTone } from '../domain/voice'
import { Badge, Empty, EmptyState, KeyValue, MetricCard, Panel, StatTile, SubCard } from './ui'
import { PageShell, Timeline } from './layout'
import { basEventEntries, severityColor } from './helpers'
import type { SafetyCommonProps } from './props'

type Props = SafetyCommonProps & {
  connected: boolean
  busy: boolean
  onStart: () => void
  onStop: () => void
  onEngineStart: () => void
  onEngineStop: () => void
}

const ACTION_LABEL: Record<string, string> = {
  PICK: 'Pick',
  PLACE: 'Place',
  OPEN: 'Open',
}

const RESULT_TONE: Record<string, string> = {
  CORRECT: '#22c55e',
  OUT_OF_SEQUENCE: '#f97316',
  WRONG_OBJECT: '#ef4444',
  WRONG_SEQUENCE: '#ef4444',
  SKIPPED: '#facc15',
  REPEATED: '#facc15',
  UNKNOWN: '#64748b',
  LOW_CONFIDENCE: '#f97316',
}

/**
 * Legacy BAS experiment demo (view 9).
 *
 * The strongest operational screen: the procedure, the feed it is judged
 * against and the classifier's reasoning share one row, so an operator can
 * see why a step was accepted or rejected without leaving the view.
 *
 * The camera panel mounts the shared `CameraStage` — the same component, the
 * same controller and the same `/api/camera/stream` connection the Mission page
 * uses. It is deliberately not a copy of that page's camera code, and it is
 * deliberately not allowed to substitute a synthetic canvas when the camera is
 * off; a view that can draw a different picture of "the camera" is a view that
 * can disagree with the rest of the app about what the crew is looking at.
 */
  export function ExperimentsView({
    state,
    engine,
    safety,
    detection,
    attendance,
    engineOffline,
    mode,
    connected,
    busy,
    onStart,
    onStop,
    onEngineStart,
    onEngineStop,
  }: Props) {
    const running = state.status === 'RUNNING'
    // The engine's own lifecycle. `running` above is the v1 local session; the
    // two used to gate the same button, which made one control the other.
    const engineRunning = engine?.status === 'RUNNING'
    const expected = expectedStep(state.experiment, state.currentStepIndex)
    const total = state.experiment.steps.length
    const done = state.completedStepIds.length
    const progress = total > 0 ? Math.round((done / total) * 100) : 0
    // Camera state comes from the one controller, not from props.
    const { phase, streamActive: cameraRunning } = useCamera()
    // Same label vocabulary and same frame information as the Mission header.
    const cameraLabel = phase === 'live' ? 'live' : phase

    // The overlay is built from the same helpers the Mission page uses, so the
    // two pages colour the same box the same way.
    const hazardLevels = useMemo(
      () => hazardLevelsFrom(safety.snapshot?.assessments),
      [safety.snapshot],
    )
    const unattendedIds = useMemo(
      () => unattendedIdsFrom(attendance.result?.watches),
      [attendance.result?.watches],
    )
    // The same resolved frame the overlay divides by, so the number in this
    // header is the number the boxes are actually scaled against.
    const frame = useMemo(
      () => resolveFrameSize(detection.result?.frameWidth, detection.result?.frameHeight),
      [detection.result?.frameWidth, detection.result?.frameHeight],
    )

    const timeline = useMemo(() => basEventEntries(state.log, 50), [state.log])
    const observed = state.currentDetected
    const classification = state.lastClassification
    const errorTotal = Object.values(state.errors).reduce((a, b) => a + b, 0)

    // The backend already split the two vocabularies; the fallback recomputes
    // from `classes` so an older payload still cannot label a `book` as an
    // experiment object.
    const experimentDets = useMemo(() => {
      const r = detection.result
      if (!r) return []
      if (r.experimentDetections) return r.experimentDetections
      const vocab = new Set(detection.status?.experimentModel?.required ?? [])
      return r.detections.filter(d => vocab.has(d.class_name))
    }, [detection.result, detection.status])
    const genericDets = useMemo(() => {
      const r = detection.result
      if (!r) return []
      if (r.genericDetections) return r.genericDetections
      const vocab = new Set(detection.status?.experimentModel?.required ?? [])
      return r.detections.filter(d => d.class_name !== 'unknown_object' && !vocab.has(d.class_name))
    }, [detection.result, detection.status])
    const readiness = detection.status?.experimentModel

  return (
    <PageShell>
      {/* ── Run summary ──────────────────────────────────────────── */}
      <div className="grid shrink-0 grid-cols-2 gap-[var(--grid-gap)] lg:grid-cols-5">
        <MetricCard
          label="Run status"
          value={state.status}
          sub={state.recording ? 'recording' : mode === 'backend' ? 'backend session' : 'local simulator'}
          color={running ? MISSION_COLORS.NORMAL : '#64748b'}
          active={running || state.recording}
        />
        <MetricCard
          label="Progress"
          value={`${done}/${total}`}
          sub={`${progress}% of the procedure matched`}
          color={progress === 100 && total > 0 ? '#22c55e' : MISSION_COLORS.OBSERVING}
          active={total > 0}
        />
        <MetricCard
          label="Sequence errors"
          value={String(errorTotal)}
          sub={`oos ${state.errors.outOfSequence} · wobj ${state.errors.wrongObject} · wseq ${state.errors.wrongSequence} · skip ${state.errors.skipped} · rep ${state.errors.repeated}`}
          color={errorTotal > 0 ? '#f97316' : '#22c55e'}
          active={errorTotal > 0}
        />
        <MetricCard
          label="Engine"
          value={engine ? engine.status.replace(/_/g, ' ') : engineOffline ? 'OFFLINE' : '—'}
          sub={
            engine
              ? `step ${(engine.current_step?.step_number ?? engine.completed_count) + 1} of ${engine.total_steps}`
              : 'no snapshot'
          }
          color={engine ? '#38bdf8' : '#64748b'}
          active={Boolean(engine)}
        />
        {/*
          Voice is its OWN state machine, not a line under the engine one.
          These used to be a single card, so "NOT STARTED" — which is the
          *experiment* state — read as the voice engine failing while the voice
          was in fact READY. The experiment can be RUNNING with voice in ERROR,
          and only a separate card can say both.
        */}
        <MetricCard
          label="Voice engine"
          value={voiceStateLabel(engine?.voice)}
          sub={voiceStateDetail(engine?.voice)}
          color={voiceStateTone(engine?.voice)}
          active={voiceState(engine?.voice) === VOICE_READY}
        />
      </div>

      {/* ── Protocol · feed · AI observation ─────────────────────── */}
      <div className="page-fill grid-cols-1 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.5fr)_minmax(0,0.95fr)]">
        {/* Protocol + procedure + controls */}
        <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="Protocol"
            right={
              <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                {state.experiment.id}
              </span>
            }
          >
            <p className="font-mono text-sm font-semibold leading-tight">{state.experiment.name}</p>
            <p className="mt-0.5 font-mono text-[10px] leading-snug text-on-surface-variant">
              {state.experiment.description}
            </p>
          </Panel>

          <Panel
            title="Procedure"
            fill
            scroll
            right={
              <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
                {done}/{total}
              </span>
            }
          >
            <ol className="rows">
              {state.experiment.steps.map((step, i) => {
                const isDone = state.completedStepIds.includes(step.id)
                const isCurrent = running && expected?.id === step.id
                return (
                  <li
                    key={step.id}
                    className="flex items-center gap-2 border px-2 py-1.5"
                    style={{
                      borderColor: isDone
                        ? 'color-mix(in oklab, #22c55e 45%, transparent)'
                        : isCurrent
                          ? 'color-mix(in oklab, var(--color-primary) 60%, transparent)'
                          : 'color-mix(in oklab, var(--t-outline-variant) 30%, transparent)',
                      background: isCurrent ? 'color-mix(in oklab, var(--color-primary) 10%, transparent)' : undefined,
                    }}
                  >
                    <span
                      className="flex h-5 w-5 shrink-0 items-center justify-center font-mono text-[10px] font-bold"
                      style={{
                        background: isDone ? '#22c55e' : isCurrent ? 'var(--color-primary)' : 'transparent',
                        border: isDone || isCurrent ? 'none' : '1px solid var(--t-outline-variant)',
                        color: isDone || isCurrent ? '#020617' : 'var(--color-on-surface-variant)',
                      }}
                    >
                      {isDone ? '✓' : i + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-[11px]">{step.label}</span>
                      <span className="block truncate font-mono text-[9px] uppercase tracking-widest text-on-surface-variant">
                        {ACTION_LABEL[step.action ?? ''] ?? step.action} · {step.activity}
                      </span>
                    </span>
                    {isCurrent && (
                      <span className="shrink-0 font-mono text-[9px] font-bold uppercase tracking-widest text-primary">
                        Next
                      </span>
                    )}
                  </li>
                )
              })}
            </ol>
          </Panel>

          <Panel title="Session Control" className="shrink-0">
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={onStart}
                disabled={mode === 'backend' ? !connected || running || busy : running || busy}
                className="btn-primary px-2 py-1.5"
              >
                <span className="msym text-base leading-none">rocket_launch</span>
                {running ? 'Running' : 'Start'}
              </button>
              <button type="button" onClick={onStop} disabled={!running || busy} className="btn-outline px-2 py-1.5">
                <span className="msym text-base leading-none">stop</span>
                Stop
              </button>
            </div>
            <div className="mt-1.5 grid grid-cols-2 gap-1.5">
              {/*
                Gated on the ENGINE's own state, not the v1 session's `running`.
                Cross-wiring them meant starting a local simulator session
                disabled the real engine start, which is exactly the control the
                operator reaches for when nothing appears to happen.
              */}
              <button
                type="button"
                onClick={onEngineStart}
                disabled={engineRunning || busy}
                className="btn-outline px-2 py-1.5"
              >
                <span className="msym text-base leading-none">account_tree</span>
                {engineRunning ? 'Engine running' : 'Engine start'}
              </button>
              <button
                type="button"
                onClick={onEngineStop}
                disabled={!engineRunning || busy}
                className="btn-outline px-2 py-1.5"
              >
                <span className="msym text-base leading-none">pause</span>
                Engine stop
              </button>
            </div>
            {mode === 'backend' && !connected && (
              <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-secondary">
                Backend offline — controls disabled.
              </p>
            )}
          </Panel>
        </div>

        {/* Feed: the one element allowed to claim leftover height */}
        <Panel
          title="Camera"
          fill
          scroll={false}
          right={
            <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
              CAM-01 · {cameraLabel} ·{' '}
              {frame ? `${frame.width}×${frame.height}` : '—'} ·{' '}
              {detection.result?.detections.length ?? 0} objects
            </span>
          }
        >
          <div className="flex min-h-0 flex-1 flex-col gap-2">
            {/*
              The shared camera, not a copy of it. `CameraStage` reads the one
              controller, opens the one MJPEG connection, derives the frame's own
              aspect and renders the shared transport, so this panel is the same
              picture as the Mission page's by construction.

              It used to be a conditional: with the camera off this panel drew a
              synthetic canvas instead, and with the camera on it passed no
              aspect lock, so `cover` cropped the 16:9 frame to whatever height
              the panel happened to have. Two different renderings of one camera,
              which is exactly the bug this block exists to prevent.
            */}
            <CameraStage
              detections={cameraRunning ? (detection.result?.detections ?? []) : []}
              unknownDetections={cameraRunning ? (detection.result?.unknownDetections ?? []) : []}
              frameWidth={cameraRunning ? (detection.result?.frameWidth ?? null) : null}
              frameHeight={cameraRunning ? (detection.result?.frameHeight ?? null) : null}
              hazardLevels={hazardLevels}
              unattendedIds={unattendedIds}
              fill
            />

            {mode === 'local' && (
              /* The procedure illustration, kept but never in the camera slot and
                 never labelled as a camera. It shows the box experiment's
                 geometry; it is not a frame, and nothing detects on it. */
              <>
                <p className="font-mono text-[10px] uppercase leading-snug tracking-wider text-on-surface-variant">
                  Procedure illustration — not a camera feed
                </p>
                <LiveFeed state={state} />
              </>
            )}
          </div>
        </Panel>

        {/* AI observation */}
        <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] gap-[var(--grid-gap)] overflow-hidden">
          <Panel
            title="AI Observation"
            fill
            scroll
            right={
              <Badge color={observed ? MISSION_COLORS.OBSERVING : '#64748b'}>
                {observed ? 'interpreting' : 'idle'}
              </Badge>
            }
          >
            {observed ? (
              <div className="stack">
                <SubCard
                  title="Current activity"
                  right={
                    <span className="font-mono text-[10px] text-on-surface-variant">
                      {Math.round(observed.confidence * 100)}%
                    </span>
                  }
                >
                  <p className="font-mono text-[11px] font-bold uppercase tracking-wider">
                    {observed.activity?.replace(/_/g, ' ') ?? 'No interpretation'}
                  </p>
                  <p className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
                    Perception emits an activity with a confidence; the state machine decides whether
                    it is valid — never the model.
                  </p>
                </SubCard>
                <SubCard
                  title="Last classification"
                  right={
                    classification?.result ? (
                      <span
                        className="font-mono text-[10px] font-bold uppercase tracking-wider"
                        style={{ color: RESULT_TONE[classification.result] ?? '#64748b' }}
                      >
                        {classification.result.replace(/_/g, ' ')}
                      </span>
                    ) : null
                  }
                >
                  {classification ? (
                    <>
                      <p className="font-mono text-[11px] font-semibold uppercase tracking-wider">
                        {classification.kind.replace(/_/g, ' ')}
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] leading-snug text-on-surface">
                        {classification.message}
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                        {classification.expected ? `expected ${classification.expected} · ` : ''}
                        {classification.confidence != null
                          ? `${Math.round(classification.confidence * 100)}%`
                          : '—'}
                      </p>
                    </>
                  ) : (
                    <p className="font-mono text-[10px] text-on-surface-variant">
                      No step has been classified yet.
                    </p>
                  )}
                </SubCard>
                {engine?.last_activity && (
                  <SubCard title="Engine last activity">
                    <KeyValue label="Step" value={engine.last_activity.label} />
                    <KeyValue label="Activity" value={engine.last_activity.activity} />
                    <KeyValue
                      label="Confidence"
                      value={`${Math.round(engine.last_activity.confidence * 100)}%`}
                    />
                  </SubCard>
                )}
                <SubCard title="Sequence error counters">
                  <div className="grid grid-cols-2 gap-[var(--row-pad)]">
                    <StatTile label="Out of sequence" value={String(state.errors.outOfSequence)} />
                    <StatTile label="Wrong object" value={String(state.errors.wrongObject)} />
                    <StatTile label="Wrong sequence" value={String(state.errors.wrongSequence)} />
                    <StatTile label="Skipped" value={String(state.errors.skipped)} />
                    <StatTile label="Repeated" value={String(state.errors.repeated)} />
                    <StatTile label="Unknown" value={String(state.errors.unknown)} />
                  </div>
                </SubCard>
                {engine && engine.violations.length > 0 && (
                  <SubCard title={`Violations (${engine.violation_count})`}>
                    <ul className="rows">
                      {engine.violations.map((v, i) => (
                        <li key={`${v.kind}-${i}`} className="truncate font-mono text-[10px]">
                          <span className="font-bold uppercase tracking-wider text-error">
                            {v.kind.replace(/_/g, ' ')}
                          </span>{' '}
                          <span className="text-on-surface-variant">{v.message}</span>
                        </li>
                      ))}
                    </ul>
                  </SubCard>
                )}
              </div>
            ) : (
              <EmptyState
                icon="psychology"
                title="No activity interpreted"
                description={
                  running
                    ? 'The perception layer has not produced an activity for the current frame. It never guesses to keep the procedure moving.'
                    : 'Start the experiment to feed frames to the perception layer.'
                }
                status={running ? 'Waiting for a valid frame' : 'Experiment not running'}
              />
            )}
          </Panel>

          <Panel title="Expected Next" className="shrink-0">
            {expected ? (
              <>
                <p className="font-mono text-[11px] font-semibold leading-tight">{expected.label}</p>
                <p className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                  step {state.currentStepIndex + 1} of {total} · {expected.activity}
                </p>
              </>
            ) : (
              <Empty label="Procedure complete — no step is expected." />
            )}
          </Panel>
        </div>
      </div>

      {/* ── Timeline + object tracking ───────────────────────────── */}
      <div
        className="page-fill shrink-0 grid-cols-1 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]"
        style={{ height: 'var(--strip-h)', flex: 'none' }}
      >
        <Panel
          title="Experiment Timeline"
          fill
          scroll
          accent={errorTotal > 0 ? '#f97316' : undefined}
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
                icon="timeline"
                title="No experiment events"
                description="Step matches, sequence violations and session transitions are recorded here in order."
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
              {experimentDets.length} exp · {genericDets.length} other
            </span>
          }
        >
          {(() => {
            const watches = attendance.result?.watches ?? []
            return (
              <div className="stack">
                {/*
                  The honesty banner. A healthy camera with a general COCO model
                  shows an EMPTY experiment panel, which is indistinguishable
                  from a broken one unless the missing capability is named.
                */}
                {readiness && !readiness.ready && (
                  <div
                    className="border px-2 py-1.5"
                    style={{
                      borderColor: 'color-mix(in oklab, #f97316 55%, transparent)',
                      background: 'color-mix(in oklab, #f97316 10%, transparent)',
                    }}
                  >
                    <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-[#f97316]">
                      {readiness.label}
                    </p>
                    <p className="mt-0.5 font-mono text-[10px] leading-snug text-on-surface">
                      The loaded model cannot emit{' '}
                      <span className="font-bold">{readiness.missing.join(', ')}</span>.
                      No object in frame can produce these classes, so this panel
                      stays empty regardless of the confidence threshold.
                    </p>
                    <p className="mt-0.5 font-mono text-[9px] uppercase tracking-widest text-on-surface-variant">
                      model {detection.status?.modelPath ?? '—'} ·{' '}
                      {detection.status?.modelType ?? '—'} ·{' '}
                      {detection.status?.classCount ?? 0} classes
                    </p>
                  </div>
                )}
                {experimentDets.length > 0 && (
                  <SubCard title={`Experiment objects (${experimentDets.length})`}>
                    <ul className="rows">
                      {experimentDets.slice(0, 8).map(d => (
                        <li key={`${d.class_name}-${d.x1}-${d.y1}`} className="truncate font-mono text-[10px]">
                          <span className="font-bold uppercase tracking-wider">{d.class_name}</span>{' '}
                          <span className="text-on-surface-variant">
                            {Math.round(d.confidence * 100)}% · {d.x1},{d.y1}–{d.x2},{d.y2}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </SubCard>
                )}
                {/*
                  Generic COCO output, listed separately and labelled as such.
                  Merging these into the experiment list is what made a `book`
                  look like the experiment container.
                */}
                {genericDets.length > 0 && (
                  <SubCard title={`Other objects — general model (${genericDets.length})`}>
                    <ul className="rows">
                      {genericDets.slice(0, 6).map(d => (
                        <li key={`${d.class_name}-${d.x1}-${d.y1}`} className="truncate font-mono text-[10px]">
                          <span className="font-bold uppercase tracking-wider text-on-surface-variant">
                            {d.class_name}
                          </span>{' '}
                          <span className="text-on-surface-variant">
                            {Math.round(d.confidence * 100)}%
                          </span>
                        </li>
                      ))}
                    </ul>
                  </SubCard>
                )}
                {watches.length > 0 && (
                  <SubCard title={`Attendance watches (${watches.length})`}>
                    <ul className="rows">
                      {watches.slice(0, 8).map(w => (
                        <li
                          key={w.instanceId}
                          className="truncate font-mono text-[10px]"
                          style={{ borderLeftWidth: 2, borderLeftColor: severityColor(w.state) }}
                        >
                          <span className="font-bold uppercase tracking-wider">{w.className}</span>{' '}
                          <span className="text-on-surface-variant">
                            {w.state.replace(/_/g, ' ')} ·{' '}
                            {w.personId ? `held by ${w.personId}` : 'no crew'}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </SubCard>
                )}
                {experimentDets.length === 0 && genericDets.length === 0 && watches.length === 0 && (
                  <EmptyState
                    compact
                    icon="track_changes"
                    title="No tracked objects"
                    description={
                      readiness && !readiness.ready
                        ? 'The loaded model has no experiment classes. General COCO objects appear separately below once detected.'
                        : 'Detected objects and their held/unattended state appear here.'
                    }
                  />
                )}
              </div>
            )
          })()}
        </Panel>
      </div>
    </PageShell>
  )
  }

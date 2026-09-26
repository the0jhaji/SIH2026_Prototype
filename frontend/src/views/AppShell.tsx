import { useEffect, useState } from 'react'
import { useCamera } from '../hooks/cameraController'
import { useDetection } from '../hooks/useDetection'
import { useExperiment } from '../hooks/useExperiment'
import { useExperimentEngine } from '../hooks/useExperimentEngine'
import { useSafety } from '../hooks/useSafety'
import { useAttendance } from '../hooks/useAttendance'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { MissionView } from './MissionView'
import { CameraView } from './CameraView'
import { AssessmentView } from './AssessmentView'
import { AstronautView } from './AstronautView'
import { AlertsView } from './AlertsView'
import { StationView } from './StationView'
import { EscalationView } from './EscalationView'
import { IncidentsView } from './IncidentsView'
import { ExperimentsView } from './ExperimentsView'
import { VIEW_DENSITY, type ViewKey } from './nav'

/**
 * The application shell owns the viewport.
 *
 * The nav and top bar are grid areas of a `100dvh` grid rather than
 * `position: fixed` overlays, and the page area is the only scrolling
 * region. Previously the body scrolled under fixed chrome, so every view
 * was a short strip at the top of an otherwise empty window.
 *
 * Note what is NOT here: any camera state. The shell used to call `useCamera`
 * and hand `camera`/`cameraRunning`/`cameraOffline`/`onCameraStart`/
 * `onCameraStop` to every view as props. That made each view responsible for
 * interpreting the camera, and they interpreted it differently. Views now read
 * the one controller themselves, and the shell only reads it for the header.
 */
export default function AppShell() {
  const [view, setView] = useState<ViewKey>('mission')
  const { state, mode, connected, busy, start, stop, setMode, safetyMessage, clearSafetyMessage } =
    useExperiment()
  const camera = useCamera()
  const detection = useDetection(mode)
  const safety = useSafety(mode)
  const attendance = useAttendance(mode)
  const engine = useExperimentEngine(mode)

  // Forward WebSocket safety messages into the polling hook for fresh updates.
  useEffect(() => {
    if (safetyMessage) {
      safety.onWsMessage(safetyMessage)
      attendance.onWsMessage(safetyMessage)
      engine.handleWsMessage(safetyMessage)
      clearSafetyMessage()
    }
  }, [safetyMessage, safety, attendance, engine, clearSafetyMessage])

  const common = {
    state,
    engine: engine.snapshot,
    engineOffline: engine.offline,
    mode,
    safety,
    attendance,
    detection,
  }

  return (
    <div className="app-shell" data-density={VIEW_DENSITY[view]}>
      <Sidebar active={view} onNavigate={setView} />
      <Header
        view={view}
        running={state.status === 'RUNNING'}
        recording={state.recording}
        mode={mode}
        connected={connected}
        busy={busy}
        camera={camera.info}
        cameraPhase={camera.phase}
        detection={detection.status}
        detectionOffline={detection.offline}
        safety={safety.snapshot}
        safetyOffline={safety.offline}
        onStart={start}
        onStop={stop}
        onModeChange={setMode}
      />

      <main className="app-main">
        {view === 'mission' && <MissionView {...common} />}
        {view === 'camera' && <CameraView {...common} />}
        {view === 'assessment' && <AssessmentView {...common} />}
        {view === 'astronaut' && <AstronautView {...common} />}
        {view === 'alerts' && <AlertsView {...common} />}
        {view === 'station' && <StationView {...common} />}
        {view === 'escalation' && <EscalationView {...common} />}
        {view === 'incidents' && <IncidentsView {...common} />}
        {view === 'experiments' && (
          <ExperimentsView
            {...common}
            connected={connected}
            busy={busy}
            onStart={start}
            onStop={stop}
            onEngineStart={engine.start}
            onEngineStop={engine.stop}
          />
        )}
      </main>
    </div>
  )
}

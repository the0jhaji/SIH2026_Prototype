import { useEffect, useState } from 'react'
import { useCamera } from '../hooks/useCamera'
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
import type { ViewKey } from './nav'

export default function AppShell() {
  const [view, setView] = useState<ViewKey>('mission')
  const { state, mode, connected, busy, start, stop, setMode, safetyMessage, clearSafetyMessage } =
    useExperiment()
  const camera = useCamera(mode)
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

  const cameraRunning = camera.info?.running === true
  const cameraOffline = camera.offline

  const common = {
    state,
    mode,
    camera: camera.info,
    cameraRunning,
    cameraOffline,
    onCameraStart: camera.start,
    onCameraStop: camera.stop,
    safety,
    attendance,
    detection,
  }

  return (
    <div className="min-h-screen bg-bg text-on-surface">
      <Sidebar active={view} onNavigate={setView} />
      <Header
        view={view}
        status={state.status}
        running={state.status === 'RUNNING'}
        recording={state.recording}
        mode={mode}
        connected={connected}
        busy={busy}
        camera={camera.info}
        cameraOffline={cameraOffline}
        detection={detection.status}
        detectionOffline={detection.offline}
        safety={safety.snapshot}
        safetyOffline={safety.offline}
        onStart={start}
        onStop={stop}
        onModeChange={setMode}
      />

      <main className="pl-24 pt-14">
        <div className="p-4">
          {view === 'mission' && <MissionView {...common} />}
          {view === 'camera' && (
            <CameraView
              {...common}
              detectionResult={detection.result}
              detectionStatus={detection.status}
              attendance={attendance.result}
              attendanceStatus={attendance.status}
            />
          )}
          {view === 'assessment' && <AssessmentView {...common} />}
          {view === 'astronaut' && <AstronautView {...common} />}
          {view === 'alerts' && <AlertsView {...common} />}
          {view === 'station' && <StationView {...common} />}
          {view === 'escalation' && <EscalationView {...common} />}
          {view === 'incidents' && <IncidentsView {...common} />}
          {view === 'experiments' && (
            <ExperimentsView
              state={state}
              mode={mode}
              camera={camera.info}
              cameraRunning={cameraRunning}
              cameraSending={camera.sending}
              cameraOffline={cameraOffline}
              onCameraStart={camera.start}
              onCameraStop={camera.stop}
              detection={detection.result}
              connected={connected}
              busy={busy}
              onStart={start}
              onStop={stop}
              engineSnapshot={engine.snapshot}
              engineOffline={engine.offline}
              onEngineStart={engine.start}
              onEngineStop={engine.stop}
            />
          )}
        </div>
      </main>
    </div>
  )
}
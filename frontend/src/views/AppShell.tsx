import { useState } from 'react'
import { useCamera } from '../hooks/useCamera'
import { useDetection } from '../hooks/useDetection'
import { useExperiment } from '../hooks/useExperiment'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { ExperimentsView } from './ExperimentsView'
import { LiveMonitorView } from './LiveMonitorView'
import { SequenceValidationView } from './SequenceValidationView'
import { LogsView } from './LogsView'
import { AnalyticsView } from './AnalyticsView'
import { SystemView } from './SystemView'
import type { ViewKey } from './nav'

export default function AppShell() {
  const [view, setView] = useState<ViewKey>('experiments')
  const { state, mode, connected, busy, start, stop, setMode } = useExperiment()
  const camera = useCamera(mode)
  const detection = useDetection(mode)

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
        onStart={start}
        onStop={stop}
        onModeChange={setMode}
      />

      <main className="pl-24 pt-14">
        <div className="p-4">
          {view === 'experiments' && (
            <ExperimentsView
              {...common}
              cameraSending={camera.sending}
              detection={detection.result}
              connected={connected}
              busy={busy}
              onStart={start}
              onStop={stop}
            />
          )}
          {view === 'live' && (
            <LiveMonitorView
              {...common}
              detection={detection.result}
              onCameraStart={camera.start}
              onCameraStop={camera.stop}
            />
          )}
          {view === 'sequence' && <SequenceValidationView state={state} />}
          {view === 'logs' && <LogsView events={state.log} />}
          {view === 'analytics' && (
            <AnalyticsView
              state={state}
              camera={camera.info}
              cameraOffline={cameraOffline}
              detection={detection.result}
              detectionStatus={detection.status}
              detectionOffline={detection.offline}
            />
          )}
          {view === 'system' && (
            <SystemView
              state={state}
              camera={camera.info}
              cameraOffline={cameraOffline}
              detection={detection.status}
              detectionOffline={detection.offline}
            />
          )}
        </div>
      </main>
    </div>
  )
}

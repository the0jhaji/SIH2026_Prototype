import { useEffect, useState } from 'react'
import type { CameraInfo } from '../domain/camera'
import type { DetectionStatus } from '../domain/detection'
import type { ExperimentState } from '../domain/types'
import { formatClock } from '../lib/time'

interface Props {
  state: ExperimentState
  camera: CameraInfo | null
  cameraOffline: boolean
  detection: DetectionStatus | null
  detectionOffline: boolean
}

export function SystemView({
  state,
  camera,
  cameraOffline,
  detection,
  detectionOffline,
}: Props) {
  const camRunning = camera?.running === true && !cameraOffline
  const inferenceOk = detection?.inferenceStatus === 'ok' && !detectionOffline
  const cores = typeof navigator !== 'undefined' ? navigator.hardwareConcurrency : undefined
  const nav = navigator as Navigator & { deviceMemory?: number }
  const deviceMem = typeof navigator !== 'undefined' ? nav.deviceMemory : undefined

  const running = state.status === 'RUNNING'
  const connected = !cameraOffline
  const frameClock = useNowClock()

  const services = [
    { name: 'API Gateway', status: connected ? 'ONLINE' : 'OFFLINE', ok: connected },
    { name: 'Camera Manager', status: camRunning ? 'STREAMING' : 'OFF', ok: camRunning },
    {
      name: 'Detection Engine',
      status: inferenceOk ? 'RUNNING' : (detection?.inferenceStatus ?? 'OFF'),
      ok: inferenceOk,
    },
    { name: 'State Machine', status: state.status, ok: running || state.status === 'COMPLETED' },
    { name: 'WebSocket', status: connected ? 'CONNECTED' : 'DOWN', ok: connected },
  ]

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MeterCard label="CPU Cores" value={cores != null ? `${cores}` : '—'} unit="cores" pct={cores ? 45 : 0} />
        <MeterCard
          label="Device Memory"
          value={deviceMem != null ? `${deviceMem}GB` : '—'}
          unit="available"
          pct={deviceMem ? 55 : 0}
        />
        <MeterCard label="Camera Load" value={camRunning ? 'STREAM' : 'IDLE'} unit="mjpeg" pct={camRunning ? 62 : 0} />
        <MeterCard label="Frame Uptime" value={frameClock} unit="session" pct={0} />
      </div>

      <section className="panel p-4">
        <h2 className="heading-title">Service Registry</h2>
        <div className="mt-3 divide-y divide-outline-variant/20">
          {services.map(s => (
            <div key={s.name} className="flex items-center justify-between py-2">
              <div className="flex items-center gap-3">
                <span
                  className={`msym text-xl leading-none ${s.ok ? 'text-primary' : 'text-outline'}`}
                >
                  {s.ok ? 'check_circle' : 'cancel'}
                </span>
                <span className="font-sans text-sm text-on-surface">{s.name}</span>
              </div>
              <span
                className={`chip px-2 py-0.5 ${
                  s.ok ? 'border-primary/50 bg-primary/10 text-primary' : 'border-error/50 bg-error/10 text-error'
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${s.ok ? 'animate-pulse bg-primary' : 'bg-error'}`} />
                {s.status}
              </span>
            </div>
          ))}
        </div>
      </section>

      <UptimeCounter />
    </div>
  )
}

function MeterCard({
  label,
  value,
  unit,
  pct,
}: {
  label: string
  value: string
  unit: string
  pct: number
}) {
  return (
    <div className="panel p-3">
      <p className="overline-label">{label}</p>
      <p className="mt-1 font-mono text-2xl font-bold tabular-nums text-primary">
        {value}
        {unit && <span className="ml-1 text-xs text-on-surface-variant">{unit}</span>}
      </p>
      {pct > 0 && (
        <div className="mt-2 h-1.5 w-full bg-surface-container-high">
          <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  )
}

function UptimeCounter() {
  const start = useRefNow()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])
  const secs = Math.max(0, Math.floor((now - start) / 1000))
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = secs % 60
  return (
    <section className="panel p-4">
      <h2 className="heading-title">Runtime Uptime</h2>
      <p className="mt-2 font-mono text-3xl font-bold tabular-nums text-primary">
        {pad(h)}:{pad(m)}:{pad(s)}
      </p>
      <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
        client session
      </p>
    </section>
  )
}

function useNowClock(): string {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])
  return formatClock(now)
}

function useRefNow(): number {
  const [v] = useState(() => Date.now())
  return v
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

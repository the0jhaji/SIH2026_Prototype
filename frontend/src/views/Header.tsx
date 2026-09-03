import { useEffect, useState } from 'react'
import type { ExperimentMode } from '../hooks/useExperiment'
import type { CameraInfo } from '../domain/camera'
import type { DetectionStatus } from '../domain/detection'
import { useTheme } from '../hooks/useTheme'
import { formatClock } from '../lib/time'
import type { ViewKey } from './nav'
import { VIEW_TITLES } from './nav'

interface Props {
  view: ViewKey
  status: string
  running: boolean
  recording: boolean
  mode: ExperimentMode
  connected: boolean
  busy: boolean
  camera: CameraInfo | null
  cameraOffline: boolean
  detection: DetectionStatus | null
  detectionOffline: boolean
  onStart: () => void
  onStop: () => void
  onModeChange: (mode: ExperimentMode) => void
}

export function Header({
  view,
  status,
  running,
  recording,
  mode,
  connected,
  busy,
  camera,
  cameraOffline,
  detection,
  detectionOffline,
  onStart,
  onStop,
  onModeChange,
}: Props) {
  const { theme, toggle } = useTheme()
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])

  const camRunning = camera?.running === true && !cameraOffline
  const detectionOk = detection?.inferenceStatus === 'ok' && !detectionOffline
  const canStart = mode === 'local' ? !running : connected && !running

  return (
    <header className="fixed inset-x-0 top-0 z-30 flex h-14 items-center border-b border-outline-variant/50 bg-surface pl-24 pr-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="font-mono text-sm font-bold uppercase tracking-[0.2em] text-primary">
          Astra AI
        </span>
        <span className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
          /&nbsp;{VIEW_TITLES[view]}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <Chip label="MISSION STATUS" value={status} running={running} accent="primary" />
        <Chip
          label="AI ENGINE"
          value={detectionOk ? detection?.detector ?? 'DETECTOR' : 'OFFLINE'}
          running={detectionOk}
          accent="tertiary"
        />
        <Chip
          label="CAM-01"
          value={camRunning ? `${camera.width}×${camera.height}` : 'OFFLINE'}
          running={camRunning}
          accent="secondary"
        />
        <Chip
          label="PROCESSING"
          value={recording ? 'REC' : busy ? 'BUSY' : 'IDLE'}
          running={recording || busy}
          accent="secondary"
        />

        <span className="mx-1 w-px self-stretch bg-outline-variant/50" />

        <span className="font-mono text-xs tabular-nums text-on-surface">
          {formatClock(now)} <span className="text-on-surface-variant">UTC</span>
        </span>

        <span className="mx-1 w-px self-stretch bg-outline-variant/50" />

        <select
          aria-label="Perception source"
          value={mode}
          onChange={e => onModeChange(e.target.value as ExperimentMode)}
          className="border border-outline-variant/60 bg-surface-container-low px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-on-surface focus:outline-none"
        >
          <option value="backend">Backend</option>
          <option value="local">Local sim</option>
        </select>

        <button
          type="button"
          onClick={toggle}
          className="btn-ghost px-2"
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
        >
          <span className="msym text-lg leading-none">
            {theme === 'dark' ? 'light_mode' : 'dark_mode'}
          </span>
        </button>

        <button
          type="button"
          onClick={onStart}
          disabled={!canStart || busy}
          className="btn-primary"
        >
          <span className="msym text-lg leading-none">play_arrow</span>
          Start
        </button>
        <button
          type="button"
          onClick={onStop}
          disabled={!running || busy}
          className="btn-outline"
        >
          <span className="msym text-lg leading-none">stop</span>
          Stop
        </button>

        <div
          className="ml-1 flex h-8 w-8 items-center justify-center border border-outline-variant/60 bg-surface-container-high font-mono text-[11px] font-bold text-primary"
          title="Operator"
        >
          OP
        </div>
      </div>
    </header>
  )
}

function Chip({
  label,
  value,
  running,
  accent,
}: {
  label: string
  value: string
  running: boolean
  accent: 'primary' | 'secondary' | 'tertiary'
}) {
  const dot = {
    primary: 'bg-primary',
    secondary: 'bg-secondary',
    tertiary: 'bg-tertiary',
  }[accent]
  return (
    <div className="hidden flex-col items-start justify-center border border-outline-variant/40 bg-surface-container-low px-2 py-1 md:flex">
      <span className="font-mono text-[8px] uppercase tracking-widest text-on-surface-variant">
        {label}
      </span>
      <span className="flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-wider text-on-surface">
        <span className={`h-1.5 w-1.5 ${running ? `${dot} animate-pulse` : 'bg-outline'}`} />
        {value}
      </span>
    </div>
  )
}

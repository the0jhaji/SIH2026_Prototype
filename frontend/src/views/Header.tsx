import { useEffect, useState } from 'react'
import type { ExperimentMode } from '../hooks/useExperiment'
import type { CameraInfo } from '../domain/camera'
import type { DetectionStatus } from '../domain/detection'
import type { SafetySnapshot } from '../domain/safety'
import { MISSION_COLORS } from '../domain/safety'
import { useTheme } from '../hooks/useTheme'
import { formatClock } from '../lib/time'
import type { ViewKey } from './nav'
import { VIEW_TITLES } from './nav'

interface Props {
  view: ViewKey
  running: boolean
  recording: boolean
  mode: ExperimentMode
  connected: boolean
  busy: boolean
  camera: CameraInfo | null
  cameraOffline: boolean
  detection: DetectionStatus | null
  detectionOffline: boolean
  safety: SafetySnapshot | null
  safetyOffline: boolean
  onStart: () => void
  onStop: () => void
  onModeChange: (mode: ExperimentMode) => void
}

export function Header({
  view,
  running,
  recording,
  mode,
  connected,
  busy,
  camera,
  cameraOffline,
  detection,
  detectionOffline,
  safety,
  safetyOffline,
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
  const mission = safetyOffline ? 'OFFLINE' : (safety?.mission_state ?? 'STANDBY')
  const missionOk = !safetyOffline && (safety?.monitoring ?? false) && !safety?.feed_stale
  const missionColor = safetyOffline ? '#64748b' : MISSION_COLORS[safety?.mission_state ?? 'NORMAL']
  const monitoring = safety?.monitoring ?? false
  const canStart = mode === 'local' ? !running : connected && !running

  return (
    <header className="app-head flex items-center gap-3 border-b border-outline-variant/50 bg-surface px-3">
      <div className="flex min-w-0 shrink items-center gap-2">
        <img
          src="/astra-logo.png"
          alt="ASTRA"
          className="size-7 shrink-0 rounded object-cover"
        />
        <span className="whitespace-nowrap font-mono text-[13px] font-bold uppercase tracking-[0.18em] text-primary">
          Astra
        </span>
        <span className="truncate font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
          /&nbsp;{VIEW_TITLES[view]}
        </span>
      </div>

      {/* The status cluster scrolls horizontally instead of pushing the
          transport controls off-screen at 1280px. */}
      <div className="scroll-x flex min-w-0 flex-1 items-center justify-end gap-1.5">
        <Chip
          label="Mission state"
          value={mission}
          running={missionOk}
          accent="primary"
          dot={missionColor}
          pulse={safety?.mission_state === 'EMERGENCY' || safety?.mission_state === 'CRITICAL'}
        />
        <Chip
          label="Monitor"
          value={monitoring ? (safety?.feed_stale ? 'stale feed' : 'online') : 'off'}
          running={monitoring && !safety?.feed_stale}
          accent="tertiary"
        />
        <Chip
          label="AI engine"
          value={
            detectionOk
              ? (detection?.detector ?? 'detector')
              : detection?.error
                ? 'error'
                : 'offline'
          }
          running={detectionOk}
          accent="tertiary"
        />
        <Chip
          label="Camera"
          value={camRunning ? `${camera.width}×${camera.height}` : 'offline'}
          running={camRunning}
          accent="secondary"
        />
        <Chip
          label="Processing"
          value={recording ? 'rec' : busy ? 'busy' : 'idle'}
          running={recording || busy}
          accent="secondary"
        />
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <span className="font-mono text-xs tabular-nums text-on-surface">
          {formatClock(now)} <span className="text-on-surface-variant">UTC</span>
        </span>

        <span className="w-px self-stretch bg-outline-variant/50" />

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
          className="btn-ghost px-1.5 py-1"
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
        >
          <span className="msym text-base leading-none">
            {theme === 'dark' ? 'light_mode' : 'dark_mode'}
          </span>
        </button>

        <button type="button" onClick={onStart} disabled={!canStart || busy} className="btn-primary px-3 py-1.5">
          <span className="msym text-base leading-none">play_arrow</span>
          Start
        </button>
        <button type="button" onClick={onStop} disabled={!running || busy} className="btn-outline px-3 py-1.5">
          <span className="msym text-base leading-none">stop</span>
          Stop
        </button>

        <div
          className="flex h-6 w-6 items-center justify-center border border-outline-variant/60 bg-surface-container-high font-mono text-[10px] font-bold text-primary"
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
  dot,
  pulse = false,
}: {
  label: string
  value: string
  running: boolean
  accent: 'primary' | 'secondary' | 'tertiary'
  dot?: string
  pulse?: boolean
}) {
  const fallback = {
    primary: 'bg-primary',
    secondary: 'bg-secondary',
    tertiary: 'bg-tertiary',
  }[accent]
  const color = dot ?? fallback
  const isHex = color.startsWith('#')
  return (
    <div className="flex shrink-0 flex-col items-start justify-center border border-outline-variant/40 bg-surface-container-low px-1.5 py-0.5">
      {/* Label only when there is width for it; below 1536px the value plus
          dot still identify the channel, and nothing is lost but repetition. */}
      <span className="hidden whitespace-nowrap font-mono text-[8px] uppercase leading-tight tracking-widest text-on-surface-variant 2xl:block">
        {label}
      </span>
      <span className="flex items-center gap-1 font-mono text-[10px] font-bold uppercase leading-tight tracking-wider text-on-surface">
        <span
          className={`h-1.5 w-1.5 shrink-0 ${running ? (pulse ? 'animate-ping' : 'animate-pulse') : 'bg-outline'} ${!isHex && running ? color : ''}`}
          style={isHex ? { background: running ? color : undefined } : undefined}
        />
        <span className="max-w-[7.5rem] truncate">{value}</span>
      </span>
    </div>
  )
}

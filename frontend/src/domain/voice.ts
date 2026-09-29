/**
 * Voice lifecycle — the states the dashboard is allowed to render.
 *
 * Mirrors `backend/app/voice_alert.py`. The vocabulary is closed on purpose:
 * a free-form health string ("initializing", "error_2") forces every view to
 * invent its own wording, which is how "NOT STARTED" ended up meaning the
 * experiment engine while the operator read it as the voice engine.
 *
 * The two are separate machines. The experiment can be RUNNING with voice in
 * ERROR, and the UI must be able to show both at once.
 */

export const VOICE_NOT_STARTED = 'NOT_STARTED' as const
export const VOICE_STARTING = 'STARTING' as const
export const VOICE_READY = 'READY' as const
export const VOICE_ERROR = 'ERROR' as const
export const VOICE_DISABLED = 'DISABLED' as const

export type VoiceState =
  | typeof VOICE_NOT_STARTED
  | typeof VOICE_STARTING
  | typeof VOICE_READY
  | typeof VOICE_ERROR
  | typeof VOICE_DISABLED

export interface VoiceStatus {
  state: VoiceState
  ready: boolean
  error: string | null
  queueSize: number
  /** Historical snake_case key, still emitted by the backend snapshot. */
  queue_size?: number
  health?: string
}

/** Rendered label for each state. */
export const VOICE_STATE_LABEL: Record<VoiceState, string> = {
  [VOICE_NOT_STARTED]: 'NOT STARTED',
  [VOICE_STARTING]: 'STARTING',
  [VOICE_READY]: 'READY',
  [VOICE_ERROR]: 'ERROR',
  [VOICE_DISABLED]: 'DISABLED',
}

/** Palette index aligned with the app's mission colours. */
export const VOICE_STATE_TONE: Record<VoiceState, string> = {
  [VOICE_NOT_STARTED]: '#64748b',
  [VOICE_STARTING]: '#facc15',
  [VOICE_READY]: '#22c55e',
  [VOICE_ERROR]: '#ef4444',
  [VOICE_DISABLED]: '#64748b',
}

/**
 * Coerce anything the API might send into a `VoiceState`.
 *
 * `READY` is derived from `ready` when present so a backend that reports
 * `state` loosely but `ready` truthfully still renders correctly. Unknown
 * values become `ERROR`, never `READY`: a state this build does not understand
 * must not be displayed as a working voice engine.
 */
export function voiceState(raw: Partial<VoiceStatus> | null | undefined): VoiceState {
  if (!raw) return VOICE_NOT_STARTED
  if (raw.state === VOICE_DISABLED) return VOICE_DISABLED
  if (raw.ready === true) return VOICE_READY
  switch (raw.state) {
    case VOICE_NOT_STARTED:
    case VOICE_STARTING:
    case VOICE_READY:
    case VOICE_ERROR:
      return raw.state
    default:
      // Unknown vocabulary: report ERROR rather than guess. A state this build
      // cannot interpret must never be rendered as a working engine.
      return VOICE_ERROR
  }
}

/** `NOT STARTED` / `STARTING` / `READY` / `ERROR` for display. */
export function voiceStateLabel(raw: Partial<VoiceStatus> | null | undefined): string {
  return VOICE_STATE_LABEL[voiceState(raw)]
}

export function voiceStateTone(raw: Partial<VoiceStatus> | null | undefined): string {
  return VOICE_STATE_TONE[voiceState(raw)]
}

/**
 * The line shown under the voice state: the real error when there is one,
 * otherwise the queue depth. Never a bare "ok" that hides a stopped worker.
 */
export function voiceStateDetail(raw: Partial<VoiceStatus> | null | undefined): string {
  const st = voiceState(raw)
  if (st === VOICE_ERROR || st === VOICE_DISABLED) {
    return raw?.error ? raw.error : 'no detail reported'
  }
  const q = raw?.queueSize ?? raw?.queue_size ?? 0
  return `queue ${q}`
}

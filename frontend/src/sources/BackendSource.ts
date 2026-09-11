import type { ExperimentState } from '../domain/types'

export interface BackendCallbacks {
  onSnapshot: (state: ExperimentState) => void
  onStatusChange: (connected: boolean) => void
  onSafetyMessage?: (message: { type: string; data?: unknown }) => void
}

/**
 * Connects to the FastAPI backend over WebSocket. The backend is the
 * authoritative state machine: it broadcasts `state` snapshots after every
 * mutation, which fully rehydrate the dashboard (including reconnect).
 *
 * Message protocol (server -> client):
 *   {"type":"state",     "data": ExperimentState}
 *   {"type":"safety",    "data": SafetySnapshot}   (mission state + assessment)
 *   {"type":"safety_event","data": SafetyEvent}    (safety log append)
 *   {"type":"attendance_event","data": AttendanceEvent} (attendance log append)
 *   {"type":"event",     "data": BasEvent}         (legacy log append)
 *   {"type":"detection", "data": Detection}        (raw perception)
 */
export class BackendSource {
  private socket: WebSocket | null = null
  private closed = false
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private readonly url: string
  private readonly callbacks: BackendCallbacks

  constructor(url: string, callbacks: BackendCallbacks) {
    this.url = url
    this.callbacks = callbacks
  }

  connect(): void {
    if (this.socket || this.closed) return
    const ws = new WebSocket(this.url)
    this.socket = ws

    ws.onopen = () => this.callbacks.onStatusChange(true)
    ws.onmessage = event => {
      let message: unknown
      try {
        message = JSON.parse(String(event.data))
      } catch {
        return
      }
      const m = message as { type?: string; data?: unknown }
      if (m?.type === 'state' && m.data) {
        this.callbacks.onSnapshot(m.data as ExperimentState)
      } else if (
        m?.type === 'safety' ||
        m?.type === 'safety_event' ||
        m?.type === 'attendance_event' ||
        m?.type === 'experiment_engine' ||
        m?.type === 'experiment_started' ||
        m?.type === 'experiment_completed' ||
        m?.type === 'experiment_reset' ||
        m?.type === 'step_candidate' ||
        m?.type === 'step_confirmed' ||
        m?.type === 'next_step' ||
        m?.type === 'out_of_sequence' ||
        m?.type === 'step_skipped' ||
        m?.type === 'repeated_step' ||
        m?.type === 'activity_uncertain'
      ) {
        this.callbacks.onSafetyMessage?.(m as { type: string; data?: unknown })
      }
    }
    ws.onerror = () => ws.close()
    ws.onclose = () => {
      this.socket = null
      this.callbacks.onStatusChange(false)
      if (!this.closed) this.scheduleReconnect()
    }
  }

  close(): void {
    this.closed = true
    if (this.retryTimer) clearTimeout(this.retryTimer)
    this.retryTimer = null
    this.socket?.close()
    this.socket = null
  }

  private scheduleReconnect(): void {
    if (this.retryTimer) return
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      this.connect()
    }, 2000)
  }
}
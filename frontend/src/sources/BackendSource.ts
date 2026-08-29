import type { ExperimentState } from '../domain/types'

export interface BackendCallbacks {
  onSnapshot: (state: ExperimentState) => void
  onStatusChange: (connected: boolean) => void
}

/**
 * Connects to the FastAPI backend over WebSocket. The backend is the
 * authoritative state machine: it broadcasts `state` snapshots after every
 * mutation, which fully rehydrate the dashboard (including reconnect).
 *
 * Message protocol (server -> client):
 *   {"type":"state",     "data": ExperimentState}
 *   {"type":"event",     "data": BasEvent}      (log append)
 *   {"type":"detection", "data": Detection}     (raw perception)
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
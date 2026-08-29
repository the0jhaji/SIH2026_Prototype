import type { Detection } from '../domain/types'
import type { EventSource } from './types'

/**
 * Real perception source for Phase 2+. Connects to the FastAPI backend over
 * WebSocket and forwards `detection` frames into the same state machine.
 */
export class WebSocketSource implements EventSource {
  readonly name = 'websocket'

  private socket: WebSocket | null = null
  private listener: ((detection: Detection) => void) | null = null
  private readonly url: string

  constructor(url: string = '/ws') {
    this.url = url
  }

  start(listener: (detection: Detection) => void): void {
    this.listener = listener
    this.socket = new WebSocket(this.url)
    this.socket.onmessage = event => {
      let data: unknown
      try {
        data = JSON.parse(String(event.data))
      } catch {
        return
      }
      const d = data as { type?: string; activity?: string | null; confidence?: number; ts?: number }
      if (d?.type !== 'detection') return
      this.listener?.({
        activity: d.activity ?? null,
        confidence: typeof d.confidence === 'number' ? d.confidence : 0,
        ts: typeof d.ts === 'number' ? d.ts : Date.now(),
      })
    }
  }

  stop(): void {
    this.listener = null
    if (this.socket) {
      this.socket.close()
      this.socket = null
    }
  }
}
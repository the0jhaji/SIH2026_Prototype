import type { Detection } from '../domain/types'

/**
 * Abstraction over whatever produces perception detections. Phase 1 ships a
 * scripted simulator; Phase 2+ supplies a WebSocket source backed by the
 * FastAPI backend. The dashboard only ever talks to this interface.
 */
export interface EventSource {
  readonly name: string
  /** Begins streaming detections to the listener. Idempotent per resolver. */
  start(listener: (detection: Detection) => void): void
  /** Stops streaming. Safe to call multiple times. */
  stop(): void
}
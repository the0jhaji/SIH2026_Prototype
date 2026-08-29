import type { Detection } from '../domain/types'
import type { EventSource } from './types'

/**
 * Phase 1 scripted perception source.
 *
 * Emits a fixed timeline of Detections chosen to exercise every supported
 * outcome of the state machine: correct step, out-of-sequence step, skipped
 * step, repeated step, unknown activity and low-confidence detection.
 *
 * These Detections are generated here (fake perception) and classified by
 * the experiment state machine, exactly like the real pipeline in later
 * phases.
 */
interface ScriptedDetection {
  delayMs: number
  activity: string | null
  confidence: number
}

export class SimulatedSource implements EventSource {
  readonly name = 'simulated'

  private timers: ReturnType<typeof setTimeout>[] = []
  private stopped = false

  start(listener: (detection: Detection) => void): void {
    if (this.stopped || this.timers.length > 0) return
    let elapsed = 800

    for (const item of SCRIPT) {
      elapsed += item.delayMs
      this.timers.push(
        setTimeout(() => {
          listener({
            activity: item.activity,
            confidence: item.confidence,
            ts: Date.now(),
          })
        }, elapsed),
      )
    }
  }

  stop(): void {
    this.stopped = true
    for (const t of this.timers) clearTimeout(t)
    this.timers = []
  }
}

const SCRIPT: ScriptedDetection[] = [
  { delayMs: 1400, activity: 'PICK_MAIN_BOX', confidence: 0.96 },
  { delayMs: 2600, activity: 'OPEN_EXPERIMENT_BOX', confidence: 0.91 },
  { delayMs: 2000, activity: 'OPEN_EXPERIMENT_BOX', confidence: 0.41 },
  { delayMs: 2200, activity: 'PICK_YELLOW_BOX', confidence: 0.88 },
  { delayMs: 2200, activity: 'PICK_RED_BOX', confidence: 0.93 },
  { delayMs: 2200, activity: 'PLACE_RED_BOX', confidence: 0.9 },
  { delayMs: 2200, activity: 'PLACE_YELLOW_BOX', confidence: 0.89 },
  { delayMs: 2200, activity: 'PICK_RED_BOX', confidence: 0.87 },
  { delayMs: 2200, activity: 'WRITING_ON_SURFACE', confidence: 0.72 },
  { delayMs: 2200, activity: 'PICK_YELLOW_BOX', confidence: 0.95 },
  { delayMs: 2200, activity: 'PLACE_YELLOW_BOX', confidence: 0.94 },
]
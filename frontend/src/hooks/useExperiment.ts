import { useCallback, useEffect, useRef, useState } from 'react'
import { INITIAL_EXPERIMENT } from '../domain/experiment'
import {
  createInitialState,
  handleDetection,
  startExperiment,
  stopExperiment,
} from '../domain/reducer'
import type { Detection, ExperimentState } from '../domain/types'
import { SimulatedSource } from '../sources/SimulatedSource'
import type { EventSource } from '../sources/types'

/**
 * Coordinates the experiment: owns the current state, routes detections from
 * the active EventSource through the state machine, and drives recording.
 *
 * Phase 1 uses the built-in simulated source. Phase 2+ swaps in the
 * WebSocket source without touching the rest of the app.
 */
export function useExperiment() {
  const [state, setState] = useState<ExperimentState>(() =>
    createInitialState(INITIAL_EXPERIMENT),
  )
  const stateRef = useRef(state)
  const sourceRef = useRef<EventSource | null>(null)

  const commit = useCallback((next: ExperimentState) => {
    stateRef.current = next
    setState(next)
  }, [])

  const stopSource = useCallback(() => {
    sourceRef.current?.stop()
    sourceRef.current = null
  }, [])

  const start = useCallback(() => {
    if (stateRef.current.status === 'RUNNING') return
    stopSource()
    commit(startExperiment(stateRef.current))
    const source: EventSource = createSource()
    sourceRef.current = source
    source.start((detection: Detection) => {
      const next = handleDetection(stateRef.current, detection)
      commit(next)
      if (next.status === 'COMPLETED') stopSource()
    })
  }, [commit, stopSource])

  const stop = useCallback(() => {
    stopSource()
    if (stateRef.current.status === 'RUNNING') commit(stopExperiment(stateRef.current))
  }, [commit, stopSource])

  useEffect(() => stopSource, [stopSource])

  return { state, start, stop }
}

/**
 * Phase selector for the perception source. Currently always simulation;
 * later phases choose the backend WebSocket (or the webcam pipeline) here.
 */
function createSource(): EventSource {
  return new SimulatedSource()
}
import { useCallback, useEffect, useRef, useState } from 'react'
import { INITIAL_EXPERIMENT } from '../domain/experiment'
import {
  createInitialState,
  handleDetection,
  startExperiment,
  stopExperiment,
} from '../domain/reducer'
import type { ExperimentState } from '../domain/types'
import { BackendSource } from '../sources/BackendSource'
import { SimulatedSource } from '../sources/SimulatedSource'
import type { EventSource } from '../sources/types'
import type { SafetyWsMessage } from './useSafety'

export type ExperimentMode = 'backend' | 'local'

/**
 * Coordinates the experiment dashboard.
 *
 * `backend` mode: the FastAPI backend owns the state machine; snapshots are
 * streamed over WebSocket and start/stop go through REST.
 *
 * `local` mode: fully client-side fallback that replays the scripted
 * simulator through the in-app reducer — independent of the backend.
 *
 * The architecture is backend-first: swap `SimulatedSource` for the future
 * OpenCV/YOLO/pose pipeline inside the backend, and this hook stays the same.
 */
export function useExperiment() {
  const [state, setState] = useState<ExperimentState>(() =>
    createInitialState(INITIAL_EXPERIMENT),
  )
  const [mode, setMode] = useState<ExperimentMode>('backend')
  const [connected, setConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [safetyMessage, setSafetyMessage] = useState<SafetyWsMessage | null>(null)

  const stateRef = useRef(state)
  const modeRef = useRef(mode)
  const backendRef = useRef<BackendSource | null>(null)
  const simRef = useRef<EventSource | null>(null)

  const commit = useCallback((next: ExperimentState) => {
    stateRef.current = next
    setState(next)
  }, [])

  useEffect(() => {
    modeRef.current = mode
  }, [mode])

  // Backend mode: open the WebSocket and hydrate from the current server state.
  useEffect(() => {
    if (mode !== 'backend') return
    const backend = new BackendSource('/ws', {
      onSnapshot: commit,
      onStatusChange: setConnected,
      onSafetyMessage: setSafetyMessage,
    })
    backendRef.current = backend
    backend.connect()
    fetch('/api/experiment/status')
      .then(response => {
        if (!response.ok) return null
        return response.json() as Promise<ExperimentState>
      })
      .then(snapshot => {
        if (snapshot) commit(snapshot)
      })
      .catch(() => {
        /* Backend offline; dashboard keeps the last known state. */
      })
    return () => {
      backend.close()
      backendRef.current = null
    }
  }, [mode, commit])

  const startLocal = useCallback(() => {
    if (stateRef.current.status === 'RUNNING') return
    commit(startExperiment(stateRef.current))
    const sim = new SimulatedSource()
    simRef.current = sim
    sim.start(detection => {
      const next = handleDetection(stateRef.current, detection)
      commit(next)
      if (next.status === 'COMPLETED') sim.stop()
    })
  }, [commit])

  const start = useCallback(() => {
    if (stateRef.current.status === 'RUNNING') return
    if (modeRef.current === 'local') {
      startLocal()
      return
    }
    if (!connected) return
    setBusy(true)
    fetch('/api/experiment/start', { method: 'POST' })
      .catch(() => {
        /* Server will raise connection state; snapshot stream resumes. */
      })
      .finally(() => setBusy(false))
  }, [connected, startLocal])

  const stop = useCallback(() => {
    if (modeRef.current === 'local') {
      simRef.current?.stop()
      simRef.current = null
      if (stateRef.current.status === 'RUNNING') commit(stopExperiment(stateRef.current))
      return
    }
    setBusy(true)
    fetch('/api/experiment/stop', { method: 'POST' })
      .catch(() => {})
      .finally(() => setBusy(false))
  }, [commit])

  const chooseMode = useCallback((next: ExperimentMode) => {
    setMode(next)
    if (next === 'local') {
      backendRef.current?.close()
      backendRef.current = null
      setConnected(false)
    }
  }, [])

  useEffect(
    () => () => {
      simRef.current?.stop()
      backendRef.current?.close()
    },
    [],
  )

  const clearSafetyMessage = useCallback(() => setSafetyMessage(null), [])

  return {
    state,
    mode,
    connected,
    busy,
    start,
    stop,
    setMode: chooseMode,
    safetyMessage,
    clearSafetyMessage,
  }
}
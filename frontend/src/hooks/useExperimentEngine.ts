import { useCallback, useEffect, useRef, useState } from 'react'
import type { ExperimentMode } from './useExperiment'
import type { VoiceStatus } from '../domain/voice'

export interface EngineStep {
  step_id: string
  activity: string
  label: string
  description: string
  step_number: number
  total_steps: number
}

export interface CompletedStep {
  step_id: string
  activity: string
  label: string
  confidence: number
  ts: string
}

export interface Violation {
  kind: string
  message: string
  ts: string
  step_id?: string
  expected_step?: string
  recovery?: string
}

export interface EngineSnapshot {
  run_id: string | null
  experiment_id: string
  experiment_name: string
  status: string
  started_at: number | null
  current_step: EngineStep | null
  next_step: EngineStep | null
  completed_steps: CompletedStep[]
  completed_count: number
  total_steps: number
  violations: Violation[]
  violation_count: number
  last_activity: { step_id: string; activity: string; label: string; confidence: number } | null
  last_alert: Violation | null
  last_event: { kind: string; [key: string]: unknown } | null
  /**
   * The voice worker's own lifecycle. Deliberately NOT the experiment's
   * `status`: a RUNNING run with an ERROR voice is a real, displayable state.
   */
  voice: VoiceStatus
}

const POLL_MS = 1000

export function useExperimentEngine(mode: ExperimentMode) {
  const [snapshot, setSnapshot] = useState<EngineSnapshot | null>(null)
  const [offline, setOffline] = useState(false)

  const fetchSnapshot = useCallback(async () => {
    try {
      const res = await fetch('/api/experiment/v2/status')
      if (!res.ok) {
        setOffline(true)
        return
      }
      const data = (await res.json()) as EngineSnapshot
      setSnapshot(data)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  const mountedRef = useRef(false)
  useEffect(() => {
    if (mode !== 'backend') return
    if (!mountedRef.current) {
      mountedRef.current = true
      fetchSnapshot()
    }
    const id = setInterval(fetchSnapshot, POLL_MS)
    return () => clearInterval(id)
  }, [mode, fetchSnapshot])

  const start = useCallback(async () => {
    try {
      await fetch('/api/experiment/v2/start', { method: 'POST' })
      await fetchSnapshot()
    } catch {
      /* offline */
    }
  }, [fetchSnapshot])

  const stop = useCallback(async () => {
    try {
      await fetch('/api/experiment/v2/stop', { method: 'POST' })
      await fetchSnapshot()
    } catch {
      /* offline */
    }
  }, [fetchSnapshot])

  const handleWsMessage = useCallback((msg: { type: string; data?: unknown }) => {
    if (msg.type === 'experiment_engine' || msg.type?.startsWith?.('experiment_')) {
      if (msg.data && typeof msg.data === 'object') {
        setSnapshot(msg.data as EngineSnapshot)
      }
    }
    if (
      msg.type === 'step_candidate' ||
      msg.type === 'step_confirmed' ||
      msg.type === 'next_step' ||
      msg.type === 'out_of_sequence' ||
      msg.type === 'step_skipped' ||
      msg.type === 'repeated_step' ||
      msg.type === 'activity_uncertain' ||
      msg.type === 'experiment_started' ||
      msg.type === 'experiment_completed' ||
      msg.type === 'experiment_reset'
    ) {
      fetchSnapshot()
    }
  }, [fetchSnapshot])

  return {
    snapshot,
    offline,
    start,
    stop,
    handleWsMessage,
  }
}

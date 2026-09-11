import { useCallback, useEffect, useState } from 'react'
import {
  SAFETY_ALERTS_URL,
  SAFETY_EVENTS_URL,
  SAFETY_INCIDENTS_URL,
  SAFETY_POLL_MS,
  SAFETY_SNAPSHOT_URL,
  SAFETY_STATION_URL,
  SAFETY_STATUS_URL,
  type Incident,
  type SafetyAlert,
  type SafetyEvent,
  type SafetySnapshot,
  type SafetyStatus,
  type StationAlert,
} from '../domain/safety'
import type { ExperimentMode } from './useExperiment'

export interface SafetyWsMessage {
  type: string
  data?: unknown
}

/**
 * Polls the backend astronaut-safety endpoints every second (backend mode
 * only, mirroring useDetection). WebSocket ``safety`` / ``safety_event``
 * messages are ingested through ``onWsMessage`` for fresher snapshots between
 * polls; the polls remain authoritative for recovery after reconnect.
 */
export function useSafety(mode: ExperimentMode) {
  const [status, setStatus] = useState<SafetyStatus | null>(null)
  const [snapshot, setSnapshot] = useState<SafetySnapshot | null>(null)
  const [alerts, setAlerts] = useState<SafetyAlert[]>([])
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [station, setStation] = useState<StationAlert[]>([])
  const [events, setEvents] = useState<SafetyEvent[]>([])
  const [busy, setBusy] = useState(false)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    if (mode !== 'backend') return
    let cancelled = false

    const poll = async () => {
      try {
        const responses = await Promise.all([
          fetch(SAFETY_STATUS_URL),
          fetch(SAFETY_SNAPSHOT_URL),
          fetch(SAFETY_ALERTS_URL),
          fetch(SAFETY_INCIDENTS_URL),
          fetch(SAFETY_STATION_URL),
          fetch(SAFETY_EVENTS_URL),
        ])
        if (!responses.every(r => r.ok)) throw new Error('bad safety response')
        const [statusJson, snapshotJson, alertsJson, incidentsJson, stationJson, eventsJson] =
          await Promise.all(responses.map(r => r.json()))
        if (cancelled) return
        setStatus(statusJson as SafetyStatus)
        setSnapshot(snapshotJson as SafetySnapshot)
        setAlerts((alertsJson as { all: SafetyAlert[] }).all)
        setIncidents((incidentsJson as { incidents: Incident[] }).incidents)
        setStation((stationJson as { feed: StationAlert[] }).feed)
        setEvents((eventsJson as { events: SafetyEvent[] }).events)
        setOffline(false)
      } catch {
        if (cancelled) return
        setStatus(null)
        setSnapshot(null)
        setOffline(true)
      }
    }

    poll()
    const timer = window.setInterval(poll, SAFETY_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [mode])

  const onWsMessage = useCallback((message: SafetyWsMessage) => {
    if (message?.type === 'safety' && message.data) {
      const next = message.data as SafetySnapshot
      setSnapshot(next)
      setStatus(prev =>
        prev
          ? {
              ...prev,
              monitoring: next.monitoring,
              mission_state: next.mission_state,
              overall_risk_level: next.overall_risk_level,
              overall_risk_score: next.overall_risk_score,
              feed_stale: next.feed_stale,
              detector: next.detector,
              detector_error: next.detector_error,
            }
          : prev,
      )
    } else if (message?.type === 'safety_event' && message.data) {
      setEvents(prev => [message.data as SafetyEvent, ...prev].slice(0, 300))
    }
  }, [])

  const ack = useCallback(async (alertId: string) => {
    setBusy(true)
    try {
      await fetch(`/api/safety/alerts/${alertId}/ack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
    } catch {
      /* Polls continue; snapshot stays honest. */
    } finally {
      setBusy(false)
    }
  }, [])

  const start = useCallback(async () => {
    setBusy(true)
    try {
      await fetch('/api/safety/start', { method: 'POST' })
    } catch {
      /* Next poll refreshes. */
    } finally {
      setBusy(false)
    }
  }, [])

  const stop = useCallback(async () => {
    setBusy(true)
    try {
      await fetch('/api/safety/stop', { method: 'POST' })
    } catch {
      /* Next poll refreshes. */
    } finally {
      setBusy(false)
    }
  }, [])

  const reset = mode !== 'backend'
  return {
    status: reset ? null : status,
    snapshot: reset ? null : snapshot,
    alerts: reset ? [] : alerts,
    incidents: reset ? [] : incidents,
    station: reset ? [] : station,
    events: reset ? [] : events,
    offline: reset ? false : offline,
    busy,
    ack,
    start,
    stop,
    onWsMessage,
  }
}
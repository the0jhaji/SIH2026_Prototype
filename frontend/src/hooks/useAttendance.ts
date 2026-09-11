import { useCallback, useEffect, useState } from 'react'
import {
  ATTENDANCE_ALERTS_URL,
  ATTENDANCE_POLL_MS,
  ATTENDANCE_STATUS_URL,
  ATTENDANCE_URL,
  type AttendanceAlert,
  type AttendanceResult,
  type AttendanceStatus,
} from '../domain/attendance'
import type { ExperimentMode } from './useExperiment'

export interface AttendanceWsMessage {
  type: string
  data?: unknown
}

/**
 * Polls the backend attendance (held/unattended) endpoints every second
 * (backend mode only). WebSocket ``attendance`` messages are ingested through
 * ``onWsMessage`` for fresher watch state between polls.
 */
export function useAttendance(mode: ExperimentMode) {
  const [status, setStatus] = useState<AttendanceStatus | null>(null)
  const [result, setResult] = useState<AttendanceResult | null>(null)
  const [alerts, setAlerts] = useState<AttendanceAlert[]>([])
  const [offline, setOffline] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (mode !== 'backend') return
    let cancelled = false

    const poll = async () => {
      try {
        const responses = await Promise.all([
          fetch(ATTENDANCE_STATUS_URL),
          fetch(ATTENDANCE_URL),
          fetch(ATTENDANCE_ALERTS_URL),
        ])
        if (!responses.every(r => r.ok)) throw new Error('bad attendance response')
        const [statusJson, resultJson, alertsJson] = await Promise.all(
          responses.map(r => r.json()),
        )
        if (cancelled) return
        setStatus(statusJson as AttendanceStatus)
        setResult(resultJson as AttendanceResult)
        setAlerts((alertsJson as { all: AttendanceAlert[] }).all)
        setOffline(false)
      } catch {
        if (cancelled) return
        setOffline(true)
      }
    }

    poll()
    const timer = window.setInterval(poll, ATTENDANCE_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [mode])

  const onWsMessage = useCallback((message: AttendanceWsMessage) => {
    if (message?.type !== 'attendance_event' || !message.data) return
    const event = message.data as AttendanceResult['events'][number]
    setResult(prev => {
      if (!prev) return prev
      return {
        ...prev,
        events: [
          ...prev.events.filter(e => e.kind !== event.kind || e.ts !== event.ts),
          event,
        ].slice(-40),
      }
    })
  }, [])

  const ack = useCallback(async (alertId: string) => {
    setBusy(true)
    try {
      await fetch(`/api/attendance/alerts/${alertId}/ack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
    } catch {
      /* Polls continue. */
    } finally {
      setBusy(false)
    }
  }, [])

  const reset = mode !== 'backend'
  return {
    status: reset ? null : status,
    result: reset ? null : result,
    alerts: reset ? [] : alerts,
    offline: reset ? false : offline,
    busy,
    ack,
    onWsMessage,
  }
}

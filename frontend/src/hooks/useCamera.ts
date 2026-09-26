import { useCallback, useEffect, useRef, useState } from 'react'
import { CAMERA_POLL_MS, type CameraInfo } from '../domain/camera'
import type { ExperimentMode } from './useExperiment'

/**
 * Polls the backend camera status and exposes Start/Stop controls.
 *
 * The camera always starts DISCONNECTED on the server (tests use a mock);
 * driving it is deliberately manual. Polling stops when the dashboard is in
 * `local` mode or the backend is unreachable.
 *
 * Two details matter for the live feed and were both wrong before:
 *
 *  1. `POST /api/camera/start` answers *before* the capture thread has
 *     flipped its flag, so its body reports `running: false`. Storing that
 *     response verbatim made the UI show "No camera feed" for a full poll
 *     interval while frames were already being served. The control call is
 *     therefore treated as intent, not as status: we re-poll immediately and
 *     never let a stale `running: false` overwrite a running camera.
 *  2. A single failed poll must not tear down a live image. A transient error
 *     marks the hook offline and keeps the last known status, so one bad
 *     response cannot blank the feed.
 */
export function useCamera(mode: ExperimentMode) {
  const [info, setInfo] = useState<CameraInfo | null>(null)
  const [offline, setOffline] = useState(false)
  const [sending, setSending] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const pollRef = useRef<() => void>(() => {})

  useEffect(() => {
    if (mode !== 'backend') return
    let cancelled = false

    const poll = async () => {
      try {
        const response = await fetch('/api/camera/status')
        if (!response.ok) throw new Error('bad camera status response')
        const data = (await response.json()) as CameraInfo
        if (cancelled) return
        setInfo(data)
        setOffline(false)
      } catch {
        if (cancelled) return
        // Keep the last known status: the feed stays up across one bad poll.
        setOffline(true)
      }
    }

    pollRef.current = () => {
      void poll()
    }
    poll()
    const timer = window.setInterval(poll, CAMERA_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [mode, refresh])

  const apply = useCallback(async (action: 'start' | 'stop') => {
    setSending(true)
    // Optimistic: the operator asked for a live frame, so ask for it now
    // instead of waiting up to CAMERA_POLL_MS for the poll to agree.
    setInfo(prev => (prev ? { ...prev, running: action === 'start' } : prev))
    try {
      const response = await fetch(`/api/camera/${action}`, { method: 'POST' })
      if (!response.ok) throw new Error('camera control failed')
      // The control response is deliberately NOT stored: the backend answers
      // before the capture thread starts, so it would report running:false.
    } catch {
      setInfo(null)
      setOffline(true)
    } finally {
      setSending(false)
      setRefresh(refresh => refresh + 1)
      pollRef.current()
    }
  }, [])

  const start = useCallback(() => apply('start'), [apply])
  const stop = useCallback(() => apply('stop'), [apply])

  return { info, offline, sending, start, stop }
}
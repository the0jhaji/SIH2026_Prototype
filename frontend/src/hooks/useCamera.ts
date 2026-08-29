import { useCallback, useEffect, useState } from 'react'
import { CAMERA_POLL_MS, type CameraInfo } from '../domain/camera'
import type { ExperimentMode } from './useExperiment'

/**
 * Polls the backend camera status and exposes Start/Stop controls.
 *
 * The camera always starts DISCONNECTED on the server (tests use a mock);
 * driving it is deliberately manual. Polling stops when the dashboard is in
 * `local` mode or the backend is unreachable.
 */
export function useCamera(mode: ExperimentMode) {
  const [info, setInfo] = useState<CameraInfo | null>(null)
  const [offline, setOffline] = useState(false)
  const [sending, setSending] = useState(false)
  const [refresh, setRefresh] = useState(0)

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
        setInfo(null)
        setOffline(true)
      }
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
    try {
      const response = await fetch(`/api/camera/${action}`, { method: 'POST' })
      if (!response.ok) throw new Error('camera control failed')
      const data = (await response.json()) as CameraInfo
      setInfo(data)
      setOffline(false)
    } catch {
      setInfo(null)
      setOffline(true)
    } finally {
      setSending(false)
      setRefresh(refresh => refresh + 1)
    }
  }, [])

  const start = useCallback(() => apply('start'), [apply])
  const stop = useCallback(() => apply('stop'), [apply])

  return { info, offline, sending, start, stop }
}
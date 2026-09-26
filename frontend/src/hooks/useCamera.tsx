import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  CAMERA_POLL_MS,
  CAMERA_STALE_MS,
  derivePhase,
  type CameraInfo,
  type CameraPhase,
} from '../domain/camera'
import { CameraContext, type CameraController } from './cameraController'

/**
 * THE canonical camera controller. One state, one poll loop, one start/stop.
 *
 * Why a provider and not a plain hook: a `useCamera()` called from two components
 * creates two independent state copies and two poll intervals, so two pages can
 * disagree about the same physical camera and every route change adds another
 * loop. Mounted once at the app root, above the view switch, it survives
 * navigation untouched — Mission -> Camera reads the same state and never re-sends
 * a start.
 *
 * The rules that keep the UI recoverable:
 *
 *  1. A failed *control* call never clears `info`. The previous hook did
 *     `setInfo(null)` on a rejected start, which blanked the status and took the
 *     CAM ON button with it — the button disappeared exactly when the operator
 *     needed it. A failure now records `errorMessage` and keeps the last known
 *     status.
 *  2. A failed *poll* never means "off". It marks the backend unreachable and
 *     keeps the last known camera state, so a brief hiccup cannot relabel a live
 *     camera as stopped.
 *  3. Nothing here reads detection. The camera is a transport; a YOLO failure
 *     must not move this state machine.
 *  4. `stale` is frame liveness, not user intent, and is derived from
 *     `frameCount` advancing. A running camera that stops delivering frames is
 *     reported stale and stays recoverable — never off.
 */
export function CameraProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<CameraInfo | null>(null)
  const [reachable, setReachable] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [isFullscreen, setFullscreen] = useState(false)
  const [pendingPhase, setPendingPhase] = useState<CameraPhase | null>(null)
  const [frameStale, setFrameStale] = useState(false)
  // `lastFrameTime` is rendered (the spec requires it in the canonical state) so
  // it must be state, not a ref. The ref mirror exists only for the staleness
  // timer, which runs outside render and must not restart on every frame.
  const [lastFrameTime, setLastFrameTime] = useState(0)

  const lastFrameCount = useRef<number | null>(null)
  const lastFrameAt = useRef(0)
  // Guards against a double click starting two capture threads.
  const inFlight = useRef(false)

  const applyInfo = useCallback((data: CameraInfo) => {
    if (!data.running) {
      lastFrameCount.current = null
      lastFrameAt.current = 0
      setLastFrameTime(0)
      setFrameStale(false)
    } else if (lastFrameCount.current === null || data.frameCount > lastFrameCount.current) {
      // A frame actually advanced: the feed is alive.
      lastFrameCount.current = data.frameCount
      const now = Date.now()
      lastFrameAt.current = now
      setLastFrameTime(now)
      setFrameStale(false)
    }
    setInfo(data)
  }, [])

  // ---- the single poll loop ------------------------------------------------
  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const response = await fetch('/api/camera/status')
        if (!response.ok) throw new Error('bad camera status response')
        const data = (await response.json()) as CameraInfo
        if (cancelled) return
        applyInfo(data)
        setReachable(true)
        if (data.status !== 'error' && !data.error) setErrorMessage(null)
      } catch {
        if (cancelled) return
        // Rule 2: unreachable is not "off". Keep the last known status on screen.
        setReachable(false)
      }
    }

    void poll()
    const timer = window.setInterval(poll, CAMERA_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [applyInfo])

  // Staleness must be re-evaluated on a timer, or a feed that dies between polls
  // would keep claiming LIVE until the next poll noticed. This reads the ref
  // mirror, so it never re-subscribes.
  useEffect(() => {
    const timer = window.setInterval(() => {
      setFrameStale(current => {
        if (lastFrameAt.current === 0) return current
        const stale = Date.now() - lastFrameAt.current > CAMERA_STALE_MS
        return stale === current ? current : stale
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])

  // ---- the single control path --------------------------------------------
  const apply = useCallback(
    async (action: 'start' | 'stop') => {
      // Block duplicate clicks while a request is in flight, so ten fast clicks
      // cannot leave two capture threads racing.
      if (inFlight.current) return
      inFlight.current = true
      setPending(true)
      setPendingPhase(action === 'start' ? 'starting' : 'stopping')
      try {
        const response = await fetch(`/api/camera/${action}`, { method: 'POST' })
        if (!response.ok) throw new Error(`camera ${action} failed`)
        setErrorMessage(null)
        // The control response is deliberately not stored: the backend answers
        // before the capture thread starts, so it reports running:false. Poll
        // instead and let the backend be the authority.
        const status = await fetch('/api/camera/status')
        if (status.ok) applyInfo((await status.json()) as CameraInfo)
        setReachable(true)
      } catch {
        // Rule 1: record the failure, never clear `info`. The controls stay put
        // and the operator can press CAM ON again.
        setErrorMessage(
          action === 'start'
            ? 'Could not reach the backend to start the camera.'
            : 'Could not reach the backend to stop the camera.',
        )
        setReachable(false)
      } finally {
        inFlight.current = false
        setPending(false)
        // Release the intent once the backend has had a chance to catch up; the
        // next poll becomes the authority.
        window.setTimeout(() => setPendingPhase(null), 600)
      }
    },
    [applyInfo],
  )

  const start = useCallback(() => {
    void apply('start')
  }, [apply])
  const stop = useCallback(() => {
    void apply('stop')
  }, [apply])

  // ---- fullscreen ----------------------------------------------------------
  // A flag, not a second camera. The existing viewport element expands in place,
  // so the same <img> keeps its single MJPEG connection and the overlay stays
  // glued to the rect it measured. No new stream, no restart.
  const exitFullscreen = useCallback(() => setFullscreen(false), [])
  const toggleFullscreen = useCallback(() => setFullscreen(v => !v), [])

  useEffect(() => {
    if (!isFullscreen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setFullscreen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isFullscreen])

  const phase = derivePhase({ info, reachable, pendingPhase, frameStale })
  const streamActive = info?.running === true
  const resolution = info ? `${info.width}×${info.height}` : null

  const value = useMemo<CameraController>(
    () => ({
      phase,
      available: reachable,
      streamActive,
      lastFrameTime,
      fps: info?.fps ?? null,
      resolution,
      errorMessage: errorMessage ?? info?.error ?? null,
      isFullscreen,
      info,
      localMode: false,
      pending,
      start,
      stop,
      toggleFullscreen,
      exitFullscreen,
    }),
    [
      phase,
      reachable,
      streamActive,
      lastFrameTime,
      errorMessage,
      info,
      isFullscreen,
      pending,
      resolution,
      start,
      stop,
      toggleFullscreen,
      exitFullscreen,
    ],
  )

  return <CameraContext.Provider value={value}>{children}</CameraContext.Provider>
}

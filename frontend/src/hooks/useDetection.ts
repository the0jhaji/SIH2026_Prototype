import { useEffect, useRef, useState } from 'react'
import {
  DETECTION_POLL_MS,
  DETECTION_STATUS_URL,
  DETECTIONS_URL,
  type DetectionResult,
  type DetectionStatus,
} from '../domain/detection'
import type { ExperimentMode } from './useExperiment'

/**
 * One short line per *change* of the detection payload, not per poll and not
 * per animation frame. This is the single place that knows what arrived from
 * the backend, so it is the only place a log is needed to answer "did the frame
 * size, the unknown feed and the size provenance reach the frontend?".
 */
function logDetectionChange(
  result: DetectionResult,
): void {
  if (!import.meta.env.DEV) return
  const { frameWidth, frameHeight, detections, unknownDetections, frameSizeSource } = result
  const frame = frameWidth && frameHeight ? `${frameWidth}x${frameHeight}` : 'null'
  console.debug(
    `[detection] frame=${frame} source=${frameSizeSource ?? 'n/a'} ` +
      `known=${detections.length} unknown=${unknownDetections.length}`,
  )
}

/**
 * Polls the backend detector status + last result every second.
 *
 * Only active in backend mode, alongside the camera poll; the detection
 * endpoints are inert-but-responding when detection is disabled (DETECTION_
 * ENABLED unset), so the panel can always render an honest state.
 */
export function useDetection(mode: ExperimentMode) {
  const [status, setStatus] = useState<DetectionStatus | null>(null)
  const [result, setResult] = useState<DetectionResult | null>(null)
  const [offline, setOffline] = useState(false)
  const signatureRef = useRef<string>('')

  useEffect(() => {
    if (mode !== 'backend') return
    let cancelled = false

    const poll = async () => {
      try {
        const [statusRes, detectionsRes] = await Promise.all([
          fetch(DETECTION_STATUS_URL),
          fetch(DETECTIONS_URL),
        ])
        if (!statusRes.ok || !detectionsRes.ok) throw new Error('bad detection response')
        const nextStatus = (await statusRes.json()) as DetectionStatus
        const nextResult = (await detectionsRes.json()) as DetectionResult
        if (cancelled) return
        setStatus(nextStatus)
        setResult(nextResult)
        setOffline(false)
        // Signature over everything the overlay depends on: the frame geometry
        // and the two feeds. Object identity churns every poll, counts do not.
        const signature = [
          nextResult.frameWidth,
          nextResult.frameHeight,
          nextResult.frameSizeSource,
          nextResult.detections.length,
          nextResult.unknownDetections.length,
        ].join(':')
        if (signature !== signatureRef.current) {
          signatureRef.current = signature
          logDetectionChange(nextResult)
        }
      } catch {
        if (cancelled) return
        setStatus(null)
        setResult(null)
        setOffline(true)
      }
    }

    poll()
    const timer = window.setInterval(poll, DETECTION_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [mode])

  // Derive the reset (non-backend) view during render instead of setState.
  const reset = mode !== 'backend'
  return {
    status: reset ? null : status,
    result: reset ? null : result,
    offline: reset ? false : offline,
  }
}
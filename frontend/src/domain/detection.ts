/** Mirror of the backend detection payloads (camelCase JSON). */

export interface Detection {
  class_name: string
  confidence: number
  x1: number
  y1: number
  x2: number
  y2: number
  timestamp: number
}

export type DetectionInferenceStatus = 'disabled' | 'idle' | 'ok' | 'error'

export interface DetectionStatus {
  enabled: boolean
  detector: string | null
  modelLoaded: boolean
  modelPath: string | null
  classes: string[] | null
  inferenceStatus: DetectionInferenceStatus
  lastInference: number | null
  detectionCount: number
  error: string | null
}

export interface DetectionResult {
  enabled: boolean
  frameWidth: number | null
  frameHeight: number | null
  detections: Detection[]
  lastInferenceMs: number | null
  inferenceMs: number | null
  inferenceStatus: DetectionInferenceStatus
  error: string | null
}

export interface DetectionBoxOverlay {
  detections: Detection[]
  frameWidth: number | null
  frameHeight: number | null
}

/** Per-class box colors used for the live-feed overlay. */
export const CLASS_COLOR: Record<string, string> = {
  person: '#34d399',
  experiment_box: '#38bdf8',
  red_box: '#f43f5e',
  yellow_box: '#fbbf24',
  target_area: '#facc15',
}

export const DETECTION_STATUS_URL = '/api/detection/status'
export const DETECTIONS_URL = '/api/detections'
export const DETECTION_POLL_MS = 1000
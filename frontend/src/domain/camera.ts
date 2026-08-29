export type CameraStatus = 'disconnected' | 'connected' | 'error'

/** Mirror of the backend `CameraManager.info()` payload (camelCase JSON). */
export interface CameraInfo {
  status: CameraStatus
  running: boolean
  source: 'webcam' | 'mock' | 'none'
  cameraIndex: number
  width: number
  height: number
  fps: number
  mock: boolean
  frameCount: number
  error: string | null
}

export const CAMERA_STREAM_URL = '/api/camera/stream'
export const CAMERA_SNAPSHOT_URL = '/api/camera/snapshot'
export const CAMERA_POLL_MS = 2500
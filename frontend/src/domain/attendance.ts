/** Mirror of the backend attendance (held/unattended) payloads (camelCase JSON). */

export interface AttendanceWatch {
  instanceId: string
  state:
    | 'UNKNOWN_DETECTED'
    | 'POSSIBLY_HELD'
    | 'HELD'
    | 'RELEASED'
    | 'UNATTENDED'
    | 'GONE'
  box: {
    class_name: string
    confidence: number
    x1: number
    y1: number
    x2: number
    y2: number
    timestamp: number
    instance_id?: string
  }
  firstSeenMs: number
  framesInState: number
  personId: string | null
  transitions: { state: string; ts: number; reason: string }[]
}

export interface AttendanceStatus {
  monitoring: boolean
  objects: number
  unattendedCount: number
  heldCount: number
  thresholds: {
    heldFrames: number
    unattendedFrames: number
    trackLostFrames: number
    armReach: number
    upperBody: number
  }
}

export interface AttendanceAlert {
  id: string
  key: string
  level: string
  title: string
  message: string
  object: string
  acknowledged: boolean
  created_at: number
  updated_at: number
}

export interface AttendanceEvent {
  kind: string
  severity: string
  instanceId?: string
  from?: string
  to?: string
  ts: number
  reason?: string
  level?: string
  alertId?: string
  message?: string
}

export interface AttendanceResult {
  watches: AttendanceWatch[]
  events: AttendanceEvent[]
}

export const ATTENDANCE_STATUS_URL = '/api/attendance/status'
export const ATTENDANCE_URL = '/api/attendance'
export const ATTENDANCE_ALERTS_URL = '/api/attendance/alerts'
export const ATTENDANCE_POLL_MS = 1000

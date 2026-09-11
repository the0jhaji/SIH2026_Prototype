/** Mirror of the backend safety payloads (camelCase JSON). */

export type RiskLevel = 'SAFE' | 'CAUTION' | 'WARNING' | 'HIGH' | 'CRITICAL'

export type MissionState =
  | 'NORMAL'
  | 'OBSERVING'
  | 'CAUTION'
  | 'WARNING'
  | 'CRITICAL'
  | 'EMERGENCY'
  | 'ACKNOWLEDGED'
  | 'RESOLVED'

export type AlertLevel = 'INFO' | 'CAUTION' | 'WARNING' | 'CRITICAL' | 'EMERGENCY'

export type Proximity = 'NEAR' | 'FAR' | 'UNKNOWN_ASTRONAUT'

export interface HazardAssessment {
  object: string
  confidence: number
  hazard: boolean
  hazard_type: string | null
  risk_level: RiskLevel
  risk_score: number
  confirmed: boolean
  frames_persisted: number
  near_astronaut: boolean
  proximity: Proximity
  moving_toward_astronaut: boolean
  reason: string
  recommended_action: string
  unclassified: boolean
  timestamp: number
  position: { x1: number; y1: number; x2: number; y2: number }
  velocity: { dx: number; dy: number; speed: number } | null
}

export interface EmergencySignal {
  event_type: string
  confirmed: boolean
  confidence: number
  description: string
  recommended_action: string
  timestamp: number
  source: string
}

export interface MonitorSnapshot {
  state: MissionState
  stateIndex: number
  activeSince: number | null
  ackedLevel: number
}

export interface SafetySnapshot {
  monitoring: boolean
  mission_state: MissionState
  environment_mode: string
  overall_risk_level: RiskLevel
  overall_risk_score: number
  feed_stale: boolean
  assessments: HazardAssessment[]
  top_hazard: HazardAssessment | null
  astronaut_in_view: boolean
  astronaut_box: {
    x1: number
    y1: number
    x2: number
    y2: number
    confidence: number
  } | null
  unclassified: string[]
  emergency: EmergencySignal | null
  monitor: MonitorSnapshot
  detector: string | null
  detector_error: string | null
  model_version: string
  timestamp: number
}

export interface EmergencyStatus {
  backend: string
  tick: number
  latestEventType: string | null
  latestConfirmed: boolean
  presentFrames: number
  absentFrames: number
  staticFrames: number
}

export interface SafetyStatus {
  monitoring: boolean
  environment_mode: string
  mission_state: MissionState
  overall_risk_level: RiskLevel
  overall_risk_score: number
  feed_stale: boolean
  detector: string | null
  detector_error: string | null
  model_version: string
  tick: number
  alerts_active: number
  incidents_open: number
  emergency: EmergencyStatus
  escalations_ready: number
  emergency_incidents: number
}

export interface SafetyAlert {
  id: string
  key: string
  level: AlertLevel
  title: string
  message: string
  event_type: string
  risk_score: number
  confidence: number
  object: string | null
  hazard_type: string | null
  recommended_action: string
  created_at: number
  updated_at: number
  acknowledged: boolean
  acked_at: number | null
  ack_note: string
  resolved: boolean
  resolved_at: number | null
  incident_id: string | null
}

export interface StationAlert {
  id: string
  incident_id: string | null
  severity: string
  event_type: string
  title: string
  message: string
  confidence: number
  timestamp: number
  source: string
}

export interface Incident {
  incident_id: string
  severity: string
  event_type: string
  timestamp: number
  confidence: number
  description: string
  recommended_action: string
  trigger_key: string
  state: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED'
  mission_state: string
  source: string
  evidence: { type: string; path: string; captured_at: number }[]
  assessment: HazardAssessment | null
  escalation: {
    status: string
    criteria: string
    path: string
    created_at: number | null
  } | null
}

export interface SafetyEvent {
  seq: number
  ts: number
  kind: string
  severity: string
  message: string
  level?: string | null
  [key: string]: unknown
}

export const SAFETY_STATUS_URL = '/api/safety/status'
export const SAFETY_SNAPSHOT_URL = '/api/safety/snapshot'
export const SAFETY_ALERTS_URL = '/api/safety/alerts'
export const SAFETY_INCIDENTS_URL = '/api/safety/incidents'
export const SAFETY_STATION_URL = '/api/safety/station'
export const SAFETY_EVENTS_URL = '/api/safety/events'
export const SAFETY_POLL_MS = 1000

/** Hex accents keyed by level/mission-state, used inline so Tailwind keeps them. */
export const RISK_COLORS: Record<RiskLevel, string> = {
  SAFE: '#22c55e',
  CAUTION: '#facc15',
  WARNING: '#f97316',
  HIGH: '#ef4444',
  CRITICAL: '#ef4444',
}

export const MISSION_COLORS: Record<MissionState, string> = {
  NORMAL: '#22c55e',
  OBSERVING: '#38bdf8',
  CAUTION: '#facc15',
  WARNING: '#f97316',
  CRITICAL: '#ef4444',
  EMERGENCY: '#dc2626',
  ACKNOWLEDGED: '#a78bfa',
  RESOLVED: '#22c55e',
}

export const ALERT_COLORS: Record<AlertLevel, string> = {
  INFO: '#64748b',
  CAUTION: '#facc15',
  WARNING: '#f97316',
  CRITICAL: '#ef4444',
  EMERGENCY: '#dc2626',
}

/** Convert a #rrggbb hex to an rgba() fill for softer backgrounds. */
export function tint(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

export function riskPercent(score: number): string {
  return `${Math.round(score * 100)}%`
}

/**
 * Share of currently assessed objects rated SAFE. Calibrated against live
 * snapshot assessments, so it updates every poll; "N/A" when nothing is
 * being assessed (never a misleading 0%).
 */
export function safePercent(assessments: SafetySnapshot['assessments'] | null | undefined): string {
  if (!assessments || assessments.length === 0) return 'N/A'
  const safe = safeCount(assessments)
  return `${Math.round((safe / assessments.length) * 100)}%`
}

/** Number of currently assessed objects rated SAFE. */
export function safeCount(assessments: SafetySnapshot['assessments'] | null | undefined): number {
  return (assessments ?? []).filter(a => a.risk_level === 'SAFE').length
}
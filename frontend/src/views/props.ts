import type { CameraInfo } from '../domain/camera'
import type { ExperimentMode } from '../hooks/useExperiment'
import type { EngineSnapshot } from '../hooks/useExperimentEngine'
import type { ExperimentState } from '../domain/types'
import type { useAttendance } from '../hooks/useAttendance'
import type { useDetection } from '../hooks/useDetection'
import type { useSafety } from '../hooks/useSafety'

export type SafetyHook = ReturnType<typeof useSafety>
export type DetectionHook = ReturnType<typeof useDetection>
export type AttendanceHook = ReturnType<typeof useAttendance>

export interface SafetyCommonProps {
  /** Experiment state-machine state (procedure + activity). */
  state: ExperimentState
  /** Richer engine snapshot when `/api/experiment/v2/status` answers. */
  engine: EngineSnapshot | null
  engineOffline: boolean
  mode: ExperimentMode
  camera: CameraInfo | null
  cameraRunning: boolean
  cameraOffline: boolean
  onCameraStart: () => void
  onCameraStop: () => void
  safety: SafetyHook
  detection: DetectionHook
  attendance: AttendanceHook
}

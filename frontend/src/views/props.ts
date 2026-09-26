import type { ExperimentMode } from '../hooks/useExperiment'
import type { EngineSnapshot } from '../hooks/useExperimentEngine'
import type { ExperimentState } from '../domain/types'
import type { useAttendance } from '../hooks/useAttendance'
import type { useDetection } from '../hooks/useDetection'
import type { useSafety } from '../hooks/useSafety'

export type SafetyHook = ReturnType<typeof useSafety>
export type DetectionHook = ReturnType<typeof useDetection>
export type AttendanceHook = ReturnType<typeof useAttendance>

/**
 * Props shared by the safety views.
 *
 * There are deliberately NO camera props here. Camera state is no longer passed
 * down: every view reads the one controller through `useCamera()`. Prop-drilling
 * it is what let the same camera read as running on the Mission page and stopped
 * on the Camera page, and it gave each view the opportunity to hide its own copy
 * of the transport.
 */
export interface SafetyCommonProps {
  /** Experiment state-machine state (procedure + activity). */
  state: ExperimentState
  /** Richer engine snapshot when `/api/experiment/v2/status` answers. */
  engine: EngineSnapshot | null
  engineOffline: boolean
  mode: ExperimentMode
  safety: SafetyHook
  detection: DetectionHook
  attendance: AttendanceHook
}

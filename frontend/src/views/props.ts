import type { CameraInfo } from '../domain/camera'
import type { ExperimentMode } from '../hooks/useExperiment'
import { useDetection } from '../hooks/useDetection'
import { useSafety } from '../hooks/useSafety'

export type SafetyHook = ReturnType<typeof useSafety>
export type DetectionHook = ReturnType<typeof useDetection>

export interface SafetyCommonProps {
  mode: ExperimentMode
  camera: CameraInfo | null
  cameraRunning: boolean
  cameraOffline: boolean
  onCameraStart: () => void
  onCameraStop: () => void
  safety: SafetyHook
  detection: DetectionHook
}
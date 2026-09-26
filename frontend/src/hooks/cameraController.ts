import { createContext, useContext } from 'react'
import type { CameraViewState } from '../domain/camera'

/**
 * The camera context and the one hook that reads it.
 *
 * This lives apart from `CameraProvider` so that neither file has to export both
 * a component and a hook: the provider owns the state machine and the poll, this
 * owns the vocabulary consumers use. Splitting them also keeps the consumer
 * surface impossible to widen — a view can read the camera or drive it, but it
 * cannot construct one.
 */
export interface CameraController extends CameraViewState {
  start: () => void
  stop: () => void
  toggleFullscreen: () => void
  exitFullscreen: () => void
  /** True while a start/stop request is in flight — blocks duplicate clicks. */
  pending: boolean
}

export const CameraContext = createContext<CameraController | null>(null)

/**
 * The only way to read or drive the camera.
 *
 * Throws outside the provider on purpose. A silent fallback is precisely how two
 * independent camera states get created: a component that quietly keeps local
 * state when the provider is missing is a component whose page disagrees with
 * every other page.
 */
export function useCamera(): CameraController {
  const controller = useContext(CameraContext)
  if (!controller) {
    throw new Error('useCamera must be used inside <CameraProvider>')
  }
  return controller
}

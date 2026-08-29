import type { ActivityId, ExperimentDef, StepDef } from './types.ts'

/**
 * Initial controlled experiment (SIH 2026 PS 26174):
 *
 *   1. Pick main experiment box
 *   2. Open experiment box
 *   3. Pick RED box
 *   4. Place RED box in target area
 *   5. Pick YELLOW box
 *   6. Place YELLOW box in target area
 *
 * The sequence lives here as pure data so it can be reconfigured or served
 * by the backend without touching application code.
 */
export const INITIAL_EXPERIMENT: ExperimentDef = {
  id: 'bas-box-sequence-01',
  name: 'BAS Box Sequence',
  description:
    'Pick the main experiment box, open it, then pick and place the RED and YELLOW boxes into the target area.',
  steps: [
    {
      id: 's1',
      activity: 'PICK_MAIN_BOX',
      label: 'Pick main experiment box',
      action: 'PICK',
      object: 'MAIN_BOX',
    },
    {
      id: 's2',
      activity: 'OPEN_EXPERIMENT_BOX',
      label: 'Open experiment box',
      action: 'OPEN',
      object: 'MAIN_BOX',
    },
    {
      id: 's3',
      activity: 'PICK_RED_BOX',
      label: 'Pick RED box',
      action: 'PICK',
      object: 'RED_BOX',
    },
    {
      id: 's4',
      activity: 'PLACE_RED_BOX',
      label: 'Place RED box in target area',
      action: 'PLACE',
      object: 'RED_BOX',
    },
    {
      id: 's5',
      activity: 'PICK_YELLOW_BOX',
      label: 'Pick YELLOW box',
      action: 'PICK',
      object: 'YELLOW_BOX',
    },
    {
      id: 's6',
      activity: 'PLACE_YELLOW_BOX',
      label: 'Place YELLOW box in target area',
      action: 'PLACE',
      object: 'YELLOW_BOX',
    },
  ],
}

export function stepForActivity(exp: ExperimentDef, activity: ActivityId): StepDef | undefined {
  return exp.steps.find(step => step.activity === activity)
}

export function expectedStep(exp: ExperimentDef, currentIndex: number): StepDef | undefined {
  return exp.steps[currentIndex]
}
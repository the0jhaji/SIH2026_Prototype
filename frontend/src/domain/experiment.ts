import type { ActivityId, EvidenceKind, ExperimentDef, StepDef } from './types.ts'

/**
 * Initial controlled experiment, mirroring `experiment/experiment.json`
 * (schemaVersion 1.1) which stays the canonical definition:
 *
 *   1. Approach the experiment area
 *   2. Open the main experiment box
 *   3. Pick RED box
 *   4. Place RED box in target area
 *   5. Pick YELLOW box
 *   6. Place YELLOW box in target area
 *   7. Both boxes placed (terminal)
 *
 * This is a CUSTOM PROTOTYPE sequence for the SIH 2026 prototype. The official
 * public problem statement is truncated after the opening sentence, so the
 * sequence is our own demonstration sequence, not the official ISRO one.
 *
 * The sequence lives here as pure data so it can be reconfigured or served
 * by the backend without touching application code.
 */
export const INITIAL_EXPERIMENT: ExperimentDef = {
  schemaVersion: '1.1',
  id: 'bas-box-handling-01',
  name: 'BAS Box Handling Experiment',
  description:
    'An astronaut approaches the experiment area, opens the main experiment box, then picks each box up and places it into the designated target area.',
  evidenceKinds: ['PRESENT', 'MOVED', 'PLACED'] as EvidenceKind[],
  evidenceNotes: {
    PRESENT: 'the class was detected this run (arrival edge, not a per-frame latch)',
    MOVED: 'the tracked class was displaced over consecutive frames (one episode per motion)',
    PLACED:
      'the tracked class came to rest inside the target area after a confirmed motion',
    KNOWN_LIMITS:
      "APPROACH is presence only - it does not prove proximity. OPEN_BOX is grounded on the first motion of a stored box (red or yellow) because no container or lid detector exists in any shipped model; it is an inference, not a measurement. HAND_NEAR_* is unavailable, so a PICK is proven by object motion only - 'held by the astronaut' is not verified.",
  },
  steps: [
    {
      id: 'step1',
      order: 1,
      activity: 'APPROACH',
      label: 'Astronaut approaches the experiment area',
      voiceInstruction: 'approach the experiment area',
      action: null,
      object: null,
      expectedObjects: ['person'],
      expectedEvents: [{ event: 'PRESENT', object: 'person' }],
    },
    {
      id: 'step2',
      order: 2,
      activity: 'OPEN_BOX',
      label: 'Astronaut opens the main experiment box',
      voiceInstruction: 'open the main experiment box',
      action: 'OPEN',
      object: 'MAIN_BOX',
      expectedObjects: ['experiment_box'],
      expectedEvents: [{ event: 'MOVED', object: ['red_box', 'yellow_box'] }],
    },
    {
      id: 'step3',
      order: 3,
      activity: 'PICK_RED',
      label: 'Astronaut picks up the red box',
      voiceInstruction: 'pick up the red box',
      action: 'PICK',
      object: 'RED_BOX',
      expectedObjects: ['red_box'],
      expectedEvents: [{ event: 'MOVED', object: 'red_box' }],
    },
    {
      id: 'step4',
      order: 4,
      activity: 'PLACE_RED',
      label: 'Astronaut places the red box into the designated target area',
      voiceInstruction: 'place the red box into the target area',
      action: 'PLACE',
      object: 'RED_BOX',
      expectedObjects: ['red_box', 'target_area'],
      expectedEvents: [{ event: 'PLACED', object: 'red_box' }],
    },
    {
      id: 'step5',
      order: 5,
      activity: 'PICK_YELLOW',
      label: 'Astronaut picks up the yellow box',
      voiceInstruction: 'pick up the yellow box',
      action: 'PICK',
      object: 'YELLOW_BOX',
      expectedObjects: ['yellow_box'],
      expectedEvents: [{ event: 'MOVED', object: 'yellow_box' }],
    },
    {
      id: 'step6',
      order: 6,
      activity: 'PLACE_YELLOW',
      label: 'Astronaut places the yellow box into the designated target area',
      voiceInstruction: 'place the yellow box into the target area',
      action: 'PLACE',
      object: 'YELLOW_BOX',
      expectedObjects: ['yellow_box', 'target_area'],
      expectedEvents: [{ event: 'PLACED', object: 'yellow_box' }],
    },
    {
      id: 'step7',
      order: 7,
      activity: 'COMPLETE',
      label: 'Both boxes are correctly placed and the experiment is complete',
      voiceInstruction: 'confirm both boxes are in the target area',
      action: null,
      object: null,
      expectedObjects: ['red_box', 'yellow_box', 'target_area'],
      // Terminal: satisfied by the placements already proven, not fresh ones.
      expectedEvents: [
        { event: 'PLACED', object: 'red_box', fresh: false },
        { event: 'PLACED', object: 'yellow_box', fresh: false },
      ],
      terminal: true,
    },
  ],
}

export function stepForActivity(exp: ExperimentDef, activity: ActivityId): StepDef | undefined {
  return exp.steps.find(step => step.activity === activity)
}

export function expectedStep(exp: ExperimentDef, currentIndex: number): StepDef | undefined {
  return exp.steps[currentIndex]
}
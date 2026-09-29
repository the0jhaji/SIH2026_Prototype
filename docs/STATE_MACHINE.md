# Experiment state machine

The state machine is the **single source of truth** for step validity. The
perception layer (simulator today, OpenCV/YOLO pipeline later) only emits raw
`Detection {activity, confidence}` values; it never decides whether a step was
correct. The frontend renders state snapshots and never classifies actions.

Implementation lives in one place per stack and **must stay in parity**:

- Python: `backend/app/state_machine.py` (authoritative — used by the server)
- TypeScript: `frontend/src/domain/reducer.ts` (used only in the offline demo
  mode; see `docs/ARCHITECTURE.md`)

## Classification outcomes

| Result (short) | Canonical event kind | When it fires                                | Progress effect        |
| -------------- | -------------------- | -------------------------------------------- | ---------------------- |
| `CORRECT`      | `STEP_MATCHED`        | detected activity equals the expected step   | advance to next step   |
| `OUT_OF_SEQUENCE` | `OUT_OF_SEQUENCE`  | known activity from a later step, with no shared action/object to be specific about | none |
| `WRONG_OBJECT` | `WRONG_OBJECT`       | same **action**, different **object** than expected (e.g. `PICK_YELLOW` while `PICK_RED` is due) | none |
| `WRONG_SEQUENCE` | `WRONG_SEQUENCE`   | same **object**, wrong **action** than expected (e.g. `PLACE_RED` before the red box was picked up) | none |
| `SKIPPED`      | `SKIPPED_STEP`        | advisory emitted with any of the three above | none                   |
| `REPEATED`     | `REPEATED_STEP`       | known activity from an already-completed step | none                 |
| `UNKNOWN`      | `UNKNOWN_ACTIVITY`    | activity is `null` or not in the experiment  | none                   |
| `LOW_CONFIDENCE` | `LOW_CONFIDENCE`    | `confidence < 0.5` (7b criterion)            | none                   |

Every classification event carries the short `result` label plus the canonical
`kind`. Lifecycle events (`EXPERIMENT_STARTED/STOPPED/COMPLETED`,
`RECORDING_STARTED/STOPPED`) carry no `result`.

## Recourse refinement

A later-than-expected detection is **refined** into a specific recourse instead
of being lumped into `OUT_OF_SEQUENCE`, so the operator is told *how* to
recover. `wrong_step_kind(expected, observed)` in
`backend/app/state_machine.py` (mirrored by `wrongStepKind` in
`frontend/src/domain/reducer.ts`) applies:

1. same `action`, different `object` -> `WRONG_OBJECT`
2. same `object`, different `action` -> `WRONG_SEQUENCE`
3. otherwise -> `OUT_OF_SEQUENCE`

Rule 3 is the honest default: refinement needs `action` **and** `object` on
both steps, so a legacy definition without that metadata always stays
`OUT_OF_SEQUENCE` rather than inventing a specific accusation.

`SKIPPED_STEP` is still emitted alongside whichever kind wins - a later step
implies earlier ones were skipped - and the generic `outOfSequence` counter
only increments when the classification really is generic. Counters are
`outOfSequence`, `wrongObject`, `wrongSequence`, `skipped`, `repeated`,
`unknown`, `lowConfidence`.

## Transition table

States: `IDLE`, `RUNNING`, `STOPPED`, `COMPLETED`.

| From            | Input                                   | Emitted events                                        | To         |
| --------------- | --------------------------------------- | ----------------------------------------------------- | ---------- |
| `IDLE`          | `start()`                               | `EXPERIMENT_STARTED`, `RECORDING_STARTED`              | `RUNNING`  |
| `RUNNING`       | detection, `conf < 0.5`                 | `LOW_CONFIDENCE`                                       | `RUNNING`  |
| `RUNNING`       | detection, null/unmapped activity       | `UNKNOWN_ACTIVITY`                                     | `RUNNING`  |
| `RUNNING`       | detection === expected step (not last)  | `STEP_MATCHED`                                         | `RUNNING`  |
| `RUNNING`       | detection === expected step (last)      | `STEP_MATCHED`, `EXPERIMENT_COMPLETED`, `RECORDING_STOPPED` | `COMPLETED` |
| `RUNNING`       | detection === already-completed step    | `REPEATED_STEP`                                        | `RUNNING`  |
| `RUNNING`       | detection === later step in sequence    | `WRONG_OBJECT` \| `WRONG_SEQUENCE` \| `OUT_OF_SEQUENCE`, then `SKIPPED_STEP` | `RUNNING` |
| `RUNNING`       | `stop()`                                | `EXPERIMENT_STOPPED`, `RECORDING_STOPPED`              | `STOPPED`  |
| `STOPPED`       | detection                               | (none; ignored)                                        | `STOPPED`  |
| `COMPLETED`     | detection                               | (none; ignored)                                        | `COMPLETED` |
| `IDLE`          | detection                               | (none; ignored)                                        | `IDLE`     |

## Semantics notes

- `SKIPPED` never fires alone: the only observable evidence of a skipped step
  is detecting a later step's activity, which also reports one of the three
  refusal kinds above.
- Progress is driven solely by `currentStepIndex`; a `STEP_MATCHED` advances it
  one position and appends the step id to `completedStepIds`. A refusal never
  advances - the offending step must be performed again.
- The expected step for corrections / voice is derived from the state machine,
  never from the frontend.
- Voice prompts come from the step's explicit `voiceInstruction` when present.
  `label` is operator-facing prose and is often third person ("Astronaut picks
  up the red box"); splitting that into an imperative produced "Please
  astronaut the picks up the red box.", so the spoken form is data. Definitions
  without `voiceInstruction` fall back to deriving it from `label`.

## Perception sources (what may fire a step)

The state machine only ever sees a `Detection`. Which source produces it
decides what the classifications above *mean*:

| `ACTIVITY_BACKEND` | Source | Step fires when |
| ------------------ | ------ | --------------- |
| `interaction` (default) | `app/interaction_perception.py` | the interaction tracker's evidence satisfies the step's `expectedEvents` |
| `live`             | `app/activity_perception.py`       | the step's `expectedObjects` are all visible on a fresh frame |
| `mock`             | `app/activity_perception.py`       | a scripted plan derived from the experiment (a mock) |
| `sim`              | `app/activity_perception.py`       | an injected script (tests/back-compat) |

Consequences worth knowing:

- `interaction` is the only source that can tell a PICK from a pass-by.
  `live` cannot, and is silent about repeats and ordering by design.
- Evidence is edge-triggered: a step consumes **one** episode, so holding an
  object in view or re-detecting it never re-fires a step. A terminal step uses
  `fresh: false` (cumulative) and is latched so it is offered exactly once.
- No grounding class may be one that no shipped detector can emit. `experiment_box`
  is declared in the object table but no shipped model produces it, so `OPEN_BOX`
  is grounded on the first stored-box motion; `test_no_step_requires_a_class_no_detector_can_see`
  in `backend/tests/test_experiment_definition.py` enforces this.
- Stale/disabled detection means no emission at all - a run waits rather than
  advancing on nothing.

## Tests

- `backend/tests/test_transitions.py` - every row of the table above,
  parametrized over every reachable position in the sequence.
- `backend/tests/test_state_machine.py` - parity with the frontend reducer, the
  refinement rule, and the voice output.
- `backend/tests/test_interaction_perception.py` - evidence-driven progression,
  including that a cumulative step is never re-offered and that one step's
  consumption cannot starve the next.
- `npm run test:reducer` - the same script, kinds, counters and voice strings as
  `test_state_machine.py`; the two must stay identical.

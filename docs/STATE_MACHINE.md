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
| `OUT_OF_SEQUENCE` | `OUT_OF_SEQUENCE`  | known activity from a later step            | none                   |
| `SKIPPED`      | `SKIPPED_STEP`        | advisory emitted with `OUT_OF_SEQUENCE`      | none                   |
| `REPEATED`     | `REPEATED_STEP`       | known activity from an already-completed step | none                 |
| `UNKNOWN`      | `UNKNOWN_ACTIVITY`    | activity is `null` or not in the experiment  | none                   |
| `LOW_CONFIDENCE` | `LOW_CONFIDENCE`    | `confidence < 0.5` (7b criterion)            | none                   |

Every classification event carries the short `result` label plus the canonical
`kind`. Lifecycle events (`EXPERIMENT_STARTED/STOPPED/COMPLETED`,
`RECORDING_STARTED/STOPPED`) carry no `result`.

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
| `RUNNING`       | detection === later step in sequence    | `OUT_OF_SEQUENCE`, `SKIPPED_STEP`                      | `RUNNING`  |
| `RUNNING`       | `stop()`                                | `EXPERIMENT_STOPPED`, `RECORDING_STOPPED`              | `STOPPED`  |
| `STOPPED`       | detection                               | (none; ignored)                                        | `STOPPED`  |
| `COMPLETED`     | detection                               | (none; ignored)                                        | `COMPLETED` |
| `IDLE`          | detection                               | (none; ignored)                                        | `IDLE`     |

## Semantics notes

- `SKIPPED` never fires alone: the only observable evidence of a skipped step
  is detecting a later step's activity, which also reports `OUT_OF_SEQUENCE`.
- Progress is driven solely by `currentStepIndex`; a `STEP_MATCHED` advances it
  one position and appends the step id to `completedStepIds`.
- The expected step for corrections / voice is derived from the state machine,
  never from the frontend.

## Tests

- `backend/tests/test_transitions.py` — every row of the table above,
  parametrized over every reachable position in the sequence (51 tests total).
- `backend/tests/test_state_machine.py` — parity with the frontend reducer and
  the spec's voice example.
- `frontend/scripts/test-reducer.mjs` (`npm run test:reducer`) — the mirror.
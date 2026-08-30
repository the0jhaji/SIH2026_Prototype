# experiment/ — BAS prototype experiment definition

This directory defines the **canonical prototype experiment** for the SIH 2026
BAS demo as machine-readable **data** (JSON), ready to be consumed by the
future activity-recognition and sequence-validation modules.

## Disclaimer — please read

The official ISRO SIH 2026 Problem Statement 26174 is publicly truncated
after:

> "You are given a box that contains two smaller boxes of color red and
> yellow..."

We therefore define **our own custom demonstration sequence** that is
*inspired by* that statement. **It is NOT the official ISRO sequence.** This
disclaimer is also embedded in `experiment.json` (`disclaimer`), so any
consumer forwards it automatically.

## Files

| File | Purpose |
| --- | --- |
| `experiment.json` | machine-readable experiment definition (see structure below) |
| `README.md` | this human-readable guide |

## The experiment (BAS Box Handling)

Initial state: a main **experiment box** contains one **red box** and one
**yellow box**. The astronaut approaches, opens it, and moves each box into the
**target area**.

| # | Activity | Expected objects | Description |
| - | -------- | ---------------- | ----------- |
| 1 | `APPROACH` | `person` | astronaut approaches the experiment area |
| 2 | `OPEN_BOX` | `experiment_box` | opens the main experiment box |
| 3 | `PICK_RED` | `red_box` | picks up the red box |
| 4 | `PLACE_RED` | `red_box`, `target_area` | places the red box into the target area |
| 5 | `PICK_YELLOW` | `yellow_box` | picks up the yellow box |
| 6 | `PLACE_YELLOW` | `yellow_box`, `target_area` | places the yellow box into the target area |
| 7 | `COMPLETE` | `red_box`, `yellow_box`, `target_area` | both boxes placed; **terminal** step |

## Objects

| classId | id | role |
| ------: | --- | ---- |
| 0 | `person` | actor |
| 1 | `experiment_box` | container |
| 2 | `red_box` | handled-object |
| 3 | `yellow_box` | handled-object |
| 4 | `target_area` | destination |

`classId` mirrors the dataset annotation classes
(`dataset/annotation/classes.json`) and the mock detector classes exactly.

## Sequence validation

Expected sequence: `APPROACH → OPEN_BOX → PICK_RED → PLACE_RED → PICK_YELLOW
→ PLACE_YELLOW → COMPLETE` (strict sequence). Classification results follow
the shared vocabulary already used by the state machine:

| Result | Event kind | When | Advances? |
| ------ | ---------- | ---- | -------- |
| `CORRECT` | `STEP_MATCHED` | matches expected step | yes |
| `OUT_OF_SEQUENCE` | `OUT_OF_SEQUENCE` | known activity from a later step | no |
| `SKIPPED` | `SKIPPED_STEP` | advisory with `OUT_OF_SEQUENCE` | no |
| `REPEATED` | `REPEATED_STEP` | activity from an already-completed step | no |
| `UNKNOWN` | `UNKNOWN_ACTIVITY` | `null` / not in experiment | no |
| `LOW_CONFIDENCE` | `LOW_CONFIDENCE` | confidence < 0.5 | no |

Worked example (from the spec):

```
Expected:      PICK_RED
Observed:      PICK_YELLOW
Result:        OUT_OF_SEQUENCE
Next expected: PICK_RED     <- the expected step does not change
```

## Not in scope (yet)

- **No** AI activity recognition — perception will later emit raw
  observations and this definition's `activities` + `steps` will drive the
  sequence-validator.
- **No** training, **no** changes to the production camera pipeline, **no**
  modifications to dataset recordings.

## Relationship to `backend/experiments/box_sequence.json`

`backend/experiments/box_sequence.json` is the *older, simplified* demo
sequence (6 steps, different activity names). It stays untouched **as a
drop-in fallback** for tooling and legacy tests. Since the Phase 5C runtime
bridge, `experiment/experiment.json` is the **runtime default**: the backend's
`load_active_experiment()` prefers it, the FastAPI app serves it via
`/api/experiment`, and the perception stage (`activity_perception.py`) derives
its live feed of detections from **this file's** `activities`/`steps` — so the
state machine, dashboard, recorder vocabulary and dataset vocabulary all read
one single source of truth.

## Validation

The definition is checked by `backend/tests/test_experiment_definition.py`
(shipped with the backend suite):

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_experiment_definition.py -q
```

Checks: JSON loads, step order is exactly 1–7, object ids and activity names
are unique, every step carries all required fields, `expectedObjects` reference
existing objects, and the validation rules / error types are consistent with
the canonical vocabulary and the worked example.
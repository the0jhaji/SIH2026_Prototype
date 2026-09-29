# Experiment detection dataset (Phase 3, human-in-the-loop)

Builds a **clean, human-verified** object-detection dataset for the ASTRA box
experiment, starting from the real recordings. It does **not** train anything
and it does **not** touch the app's runtime detector yet.

The rule everything here obeys: **a proposal is not ground truth.** Automatic
detectors suggest boxes; a human decides. A frame only becomes a training row
once a person has marked it reviewed, and `experiment_tool.label_rows` ignores
everything else.

## Why this exists (audit summary)

`dataset/experiment_train/` and `models/detection/experiment_custom.onnx` are
**not** usable as a starting point:

| Finding | Consequence |
|---|---|
| `experiment_train` has 280 images / 280 labels / 516 boxes, **all class 0** | `yellow_box` had zero examples, so it could never be learned |
| No exact image-hash match to any recording | the provenance is unknown, so it cannot be audited |
| `experiment_custom.onnx` found 3 `red_box` and **0** `yellow_box` over 98 named frames | the shipped model does not solve the task |
| Raw colour heuristics jumped 697 px between frames and fired on skin/clothing | automation cannot be trusted to label |

So the dataset is rebuilt from the recordings, and a human confirms every box.

## Vocabulary (locked)

`dataset/experiment_detection/classes.json` is the contract. Index = YOLO class id.

| id | class | proposed automatically? |
|---|---|---|
| 0 | `person` | yes — COCO `yolov8n.onnx` |
| 1 | `main_experiment_box` | **no** — no reliable heuristic is known |
| 2 | `red_box` | yes — saturated red HSV (catches skin/clothing; human must confirm) |
| 3 | `yellow_box` | yes — saturated yellow HSV (same caveat) |
| 4 | `red_target_area` | **no** — a placement region, drawn by hand |
| 5 | `yellow_target_area` | **no** — same |

`opened_box`, `held_red_box`, `held_yellow_box` and the actions (`PICK_RED`,
`PLACE_RED`, …) are **not** classes. One frame cannot prove that a box is held
or was placed; a single-frame detector trained on those states would be learning
to guess an action. The model answers *what is visible and where*; temporal
logic over consecutive frames answers *what is happening*.

## Layout

```
dataset/experiment_detection/
  classes.json                  the locked vocabulary
  index.json                    every recorded session and frame (no labels)
  selection.json                which frames were chosen for review
  dataset_report.json           counts written by the validator
  images/{train,val,test}/      created, deliberately EMPTY (no split yet)
  labels/{train,val,test}/      created, deliberately EMPTY (no split yet)
  labels/staging/<session>/     confirmed YOLO labels, still unsplit
  metadata/<session>.json       session, frame, source, review state, activity
  proposals/<session>/*.json    candidate boxes — never ground truth
  sampling/<session>.{json,jpg} review order + a contact sheet
  qa/<session>.jpg              confirmed labels drawn back onto the frames
```

Splitting by **session** (not by frame) is the only defensible split, and one
recording cannot support an honest train/val/test split. The directories exist
so the structure is ready, and they stay empty until there are enough complete
sessions. `test_experiment_dataset.py` enforces this.

## Commands

Run from the repo root with the backend venv.

```powershell
# 1. index the recordings and choose frames to review (contact sheets included)
.\.venv\Scripts\python.exe experiment\yolo_training\sample_frames.py

# 2. generate candidate boxes for those frames
.\.venv\Scripts\python.exe experiment\yolo_training\prelabel.py --sampled-only

# 3. human annotation
.\.venv\Scripts\python.exe experiment\yolo_training\annotate.py
#    then open http://127.0.0.1:8002/

# 4. check the confirmed labels
.\.venv\Scripts\python.exe experiment\yolo_training\validate_annotations.py

# 5. look at them: valid geometry is not the same as a correct label
.\.venv\Scripts\python.exe experiment\yolo_training\visualize_annotations.py --per-frame

# review state (read-only first)
.\.venv\Scripts\python.exe experiment\yolo_training\review_frames.py --list

# tests
.\.venv\Scripts\python.exe -m pytest experiment\yolo_training\tests -q
```

`prelabel.py` also accepts `--session <id>`, `--no-person` (colour heuristics
only) and `--model <path>`. A missing model disables person proposals instead of
failing, and never invents boxes.

## Review state

`reviewed` is the difference between a human's work and a training row, so it is
treated as a first-class, durable decision:

- It is keyed on **session + frame id** (`metadata/<session>.json` →
  `frames["74"]`, `labels/staging/<session>/frame_000074.txt`), never on the
  filename alone — every session has its own `frame_000074.txt`.
- Ticking the box **persists immediately** via `POST /api/review`, so it
  survives navigation, a refresh and a crash. It is deliberately decoupled from
  Save: the decision is about the frame, not about its boxes, so it can be
  recorded (or repaired) without redrawing anything.
- The checkbox is populated from the server on load and **never defaults to
  checked**. Save reports the stored state explicitly: an unreviewed save says
  so instead of claiming plain success. (The earlier version re-derived the
  checkbox on every frame load and auto-advanced after saving, so a whole run of
  finished labels was stored with `reviewed=false` and the validator rejected it.)
- `experiment_tool.annotation_state` is the single source of truth, read by both
  the UI and the validator, so "is this frame reviewed" cannot mean two different
  things.
- Validator errors are keyed `session frame <id>`, never the bare filename.
- Duplicate frame ids inside one session are rejected at index time, because two
  files claiming the same number would overwrite each other's labels.

If labels exist but a review decision was lost, recover it without redrawing:

```powershell
.\.venv\Scripts\python.exe experiment\yolo_training\review_frames.py --list
.\.venv\Scripts\python.exe experiment\yolo_training\review_frames.py --mark-reviewed
```

`--mark-reviewed` only promotes frames that **already have a label file** and
never rewrites the YOLO text, so no box coordinate can change. It can therefore
never invent an annotation.

## Annotator controls

| key | action |
|---|---|
| `1`–`6` | select class for the next box |
| `N` / `P` | next / previous frame |
| `D`, `Delete`, `Backspace` | delete the selected box |
| `S` | save |
| double-click a dashed box | accept that proposal |

Draw by dragging on the canvas, move by dragging inside a box, resize from a
corner or edge handle, and reclassify by selecting a box and pressing the new
class key. Proposals are drawn **dashed** and are only copied into the label list
when accepted. "reviewed" can be unticked to save a frame as *not yet* decided;
unticked frames are excluded from `label_rows`.

Frames the human has confirmed are also written to `labels/staging/<session>/` in
YOLO text, with a blank (empty) file for a genuine background frame — that is
valid negative data, not a missing label.

## Current state

Generated, before any human work:

- 11 recorded sessions / 845 source frames (7 of them activity-segmented)
- 186 frames selected for review, plus 4 high-motion frames per session
- proposals on 186/186 frames: 185 `person`, 495 `red_box`, 166 `yellow_box`

After the first annotation pass:

- **28 reviewed frames, 60 confirmed boxes** in
  `session_20260829_233703_6weu`: 17 `person`, 22 `main_experiment_box`,
  3 `red_box`, 8 `yellow_box`, 3 `red_target_area`, 7 `yellow_target_area`
- 10 of 11 sessions are still untouched

The `red_box` proposal count is far above the number of real red boxes: that is
the heuristic catching skin and clothing, exactly as the audit predicted. Delete
them in the annotator.

## Next phase (not started)

Only after a human has confirmed labels: split by session, write the
`data.yaml`, fine-tune in `.venv-train` (Ultralytics, CPU), then integrate
through the **existing** `DetectionService` (`DETECTION_BACKEND=dual`) feeding the
existing tracker and `ExperimentSession`. No second camera pipeline, no second
procedure controller.

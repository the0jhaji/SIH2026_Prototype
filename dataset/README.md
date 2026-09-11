# dataset/ — Local BAS experiment dataset

Collects a **custom, local-only** dataset for training the Astra AI object
detector (the phase after this one). Everything stays on this machine — there
is **no upload, no cloud, no network dependency** in the recorder.

## Structure

| Path | Purpose |
| --- | --- |
| `raw/`             | untouched recording **sessions** (one directory per take) |
| `frames/`          | curated/organized frames ready for training (filled in a later phase) |
| `annotations/`     | YOLO label files mirroring `raw/` paths (`class cx cy w h`, normalized 0–1) |
| `train/ val/ test/`| **session-aware** split output (created by `prepare_split.py`) |
| `scripts/record_dataset.py` | recorder CLI (Phase 4A) |
| `activity/` | activity dataset: `activity/<ACTIVITY>/session_*/` (JPEG + manifest + metadata) |
| `scripts/record_activity.py` | activity recorder CLI (Phase 5B) |
| `scripts/prepare_split.py`  | split raw+annotations into train/val/test by session (Phase 4B) |
| `scripts/validate_dataset.py` | dataset + split validation CLI (Phase 4B) |
| `scripts/export_training.py` | write a validated ultralytics `data.yaml` from the split (Phase 4C) |
| `scripts/install_detection_model.py` | install a trained ONNX + `.names` into `models/detection/` (Phase 4C) |
| `training_tool.py`  | shared Phase 4C logic: data.yaml export, class histogram, model install (pure, testable) |
| `requirements-train.txt` | **optional** ultralytics trainer env (runtime never needs it) |
| `roboflow/`         | downloaded **everyday-objects** export (train/valid + `data.yaml`); `roboflow/split/` is the prepared train/val/test (Phase 4C+) — separate from the app's `raw/` object set |
| `roboflow_tool.py`  | shared **roboflow bridge**: flat-export split, detection-label normalisation (drops seg-polygon rows), data.yaml, model install (pure, testable) |
| `scripts/prepare_roboflow.py` | build `roboflow/split/{train,val,test}` + `data.yaml` from the download |
| `scripts/train_roboflow.py`   | lightweight ultralytics trainer (`yolov8n`, small epochs default) for the roboflow split |
| `scripts/evaluate_roboflow.py` | score a trained ONNX through the real runtime detector on the test holdout |
| `dataset_tool.py`  | shared capture logic: session creation, metadata, manifest (pure, testable) |
| `annotation/`      | dev-only browser annotation tool (stdlib `http.server`, no new deps) + `annotator.py` shared logic |
| `tests/`           | session/config + annotation/split/validation tests (no camera/device needed) |

## Requirements

The recorder reuses the **exact camera configuration** of the production
backend (`backend/camera/capture.py`, defaults: webcam index `0`,
`1280×720 @ 30fps`). Use the backend venv (it already has OpenCV):

```powershell
.\.venv\Scripts\python.exe dataset\scripts\record_dataset.py          # backend venv, from repo root
```

## Recording

```
usage: record_dataset.py [--camera-index N] [--width W] [--height H] [--fps F]
                         [--interval SECONDS] [--label NAME] [--output DIR] [--mock]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--camera-index` | `0` | webcam device index |
| `--width` / `--height` | `1280×720` | capture resolution |
| `--fps` | `30` | capture frame rate |
| `--interval` | `1.0` | seconds between **saved** frames while recording (0.5 is handy for quick action takes) |
| `--label` | `misc` | activity/object class; slugified into the session path (`PICK_RED_BOX` → `raw/pick_red_box/…`) |
| `--output` | `dataset/` | dataset root; sessions land under `raw/<label>/` |
| `--mock` | off | synthetic mock camera — no webcam needed (for smoke-testing) |

A live preview window shows the camera, a real-time FPS readout, the frames
saved so far, and the save interval. Keys:

- **SPACE** — start / stop recording
- **Q** or **ESC** — quit (releases the camera, writes final metadata)

### Example

```powershell
# One label per activity/pose; record several takes per label.
.\.venv\Scripts\python.exe dataset\scripts\record_dataset.py --label PICK_RED_BOX --interval 0.5
.\.venv\Scripts\python.exe dataset\scripts\record_dataset.py --label PLACE_RED_BOX --interval 0.5
```

Each session is a fresh directory:

```
dataset/raw/pick_red_box/session_20260829_143051_a3f9/
    frame_000001.jpg   # one JPEG per interval tick
    frame_000002.jpg
    …
    manifest.csv       # nickname per saved frame: index, ISO time, epoch-ms
    metadata.json      # camera config, interval, label, frames saved, session id
```

`metadata.json` is written when the session starts and refreshed on quit
(with `ended_at` and the final `frames_saved`), so every take is
self-describing.

## Guidance

- Keep the background/lab lighting and table layout similar to the real
  deployment camera so the trained model generalizes.
- Record both the action and a short idle/"empty" take per scene (an
  `empty` label helps the detector learn negatives).
- The recorder never alters `dataset/raw/` sessions; curation and labeling
  happen in later phases into `frames/` + `annotations/`.

## Annotating (Phase 4B)

A small browser tool annotates the raw frames **locally** — no cloud, no
external API, no AI API. It is independent of the production BAS app.

```powershell
.\.venv\Scripts\python.exe dataset\annotation\app.py        # backend venv, repo root
# opens http://127.0.0.1:8700 ; Ctrl+C stops the server
```

Controls: drag to draw a box · click a box to select it · legends/number keys
`0`–`4` set the draw class or change the selected box's class.

| Key | Action |
| --- | --- |
| `N` | next image |
| `P` | previous image |
| `S` | save current image (YOLO label) |
| `D` | delete selected box |
| `C` | clear all boxes on the current image |
| `Q` | close the tab |

Saved labels land in `dataset/annotations/<session>/frame_XXXXXX.txt`
(`class cx cy w h`, normalized 0–1), mirroring the `raw/` paths. The top bar
shows `Annotated: X / Y · Progress: Z%`. The **class list is config data** in
`dataset/annotation/classes.json`; edit it to add/rename classes (its index is
the YOLO class id).

Everything is validated on draw (min box size, clamped to the frame) and again
server-side before saving (class id in range, coords in [0,1], positive size).

## Dataset split (Phase 4B)

`prepare_split.py` splits **whole recording sessions** — never individual
frames from the same session across sets. Defaults to 70 / 20 / 10.

```powershell
.\.venv\Scripts\python.exe dataset\scripts\prepare_split.py --root dataset
.\.venv\Scripts\python.exe dataset\scripts\prepare_split.py --root dataset --seed 7 --test 0.15
```

Output (originals are only copied, never modified):

```
dataset/train/{images,labels}/<session>/…      dataset/val/...      dataset/test/...
dataset/split_manifest.json   # seed + session → split
```

## Validate dataset (Phase 4B)

```powershell
.\.venv\Scripts\python.exe dataset\scripts\validate_dataset.py --root dataset
```

Checks: image + label files exist, labels are well-formed YOLO with valid
class ids, coordinates in [0,1], positive width/height, boxes inside the
frame, no orphaned labels — and **session leakage** (one session across
multiple splits). Prints a summary; exit code `0` = clean, `1` = errors.
Splits with images that have no label file are reported as errors (blank
labels are fine for intentionally empty frames).

## Training export (Phase 4C)

Bridges the annotated split to model training — and the trained model back to
the running app. **No training happens here** (that needs ultralytics, which
is kept out of the core venv); this validates the data and formats it exactly
as the trainer expects.

```powershell
# 1. Export a validated data.yaml from the annotated split:
.\\.venv\\Scripts\\python.exe dataset\\scripts\\export_training.py --root dataset
#    -> dataset/training/data.yaml
#    Exit 2 = not trainable yet: missing label files, out-of-range class ids,
#    malformed boxes, or a session spanning more than one split.
```

The generated `data.yaml` points `path` at the dataset root and
`train/val/test` at the `*/images` dirs, with `nc`/`names` from
`annotation/classes.json` — index-aligned with the annotation tool. `test`
is omitted when the split has no test images (train/val are always required).

```powershell
# 2. Train + export ONNX in a dedicated venv (see requirements-train.txt):
.venv-train\\Scripts\\yolo train data=dataset\\training\\data.yaml model=yolov8n.pt epochs=200 imgsz=640
.venv-train\\Scripts\\yolo export model=runs/detect/train/weights/best.pt format=onnx

# 3. Install the ONNX + its .names for the runtime:
.\\.venv\\Scripts\\python.exe dataset\\scripts\\install_detection_model.py --onnx runs/detect/train/weights/best.onnx
#    -> models/detection/yolov8n.onnx + models/detection/yolov8n.names (from classes.json)

# 4. Run the backend with DETECTION_ENABLED=true DETECTION_BACKEND=yolo; the
#    runtime reads the ONNX and the .names file (ai/detection/yolo_detector.py).
```

Full flow, runtime config, and behavioural notes: `models/detection/README.md`.

## Activity dataset (Phase 5B)

Collects the **ACTION dataset** for a later activity-recognition +
sequence-validation phase. Units are recordings of a single named activity
(the 7-step box-handling experiment), captured with the same proven recorder
style as the object dataset. Local-only, like everything else here.

### Purpose

The object dataset (`raw/`) teaches a detector to *see* boxes and the
astronaut. The activity dataset (`activity/`) records *what is happening over
time* — one activity per take — so a temporal model can classify
`APPROACH … COMPLETE` actions from frame sequences. No AI inference and no
training happen in this phase.

### Directory structure

Valid activity names are loaded from the **canonical
`experiment/experiment.json`** definition (`activities` list) — the recorder
and tests never hardcode the vocabulary. For each recorded take, one unique
session directory is created:

```
dataset/activity/<ACTIVITY>/session_<timestamp>_<random>/
    frame_000001.jpg   # one JPEG per interval tick
    frame_000002.jpg
    …
    manifest.csv       # index, timestamp ISO, epoch-ms, filename
    metadata.json      # activity, session id, started/ended, camera, interval, frame_count, source
```

### Recorder

```powershell
backend\.venv\Scripts\python.exe dataset\scripts\record_activity.py --activity PICK_RED --interval 0.1
```

`--activity` is required; choices come straight from `experiment/experiment.json`
(an invalid name is rejected by the CLI). Flags match `record_dataset.py`:
`--camera-index`, `--width`, `--height`, `--fps`, `--interval`, `--output`,
`--mock`. The camera layer is reused from the backend
(`backend/camera/capture.py`). The HUD shows the **activity name** up front,
plus STATUS / SAVED / FPS / INTERVAL / ELAPSED; **SPACE** starts/stops
recording, **Q/ESC** quits and writes final metadata.

### Valid activities

From `experiment/experiment.json` (prototype experiment — see disclaimer):

| Activity | Meaning |
| --- | --- |
| `APPROACH` | astronaut enters the experiment area |
| `OPEN_BOX` | main experiment box is opened |
| `PICK_RED` | red box is picked up |
| `PLACE_RED` | red box is placed into the target area |
| `PICK_YELLOW` | yellow box is picked up |
| `PLACE_YELLOW` | yellow box is placed into the target area |
| `COMPLETE` | both boxes placed; experiment finished |

### Recommended collection procedure

- Record **multiple takes of the same activity** in different sessions (e.g.
  5+ per activity) so a sequence/temporal model sees varied timing and poses.
- Run one activity per take; keep each take focused (start the take just
  before the action begins, stop just after it ends).
- Use a low interval (e.g. `0.1s…0.5s`) for quick actions like pick/place.
- Keep the same lab lighting / table layout as the object dataset so detector
  features transfer.
- This sequence is **your own prototype experiment definition**, inspired by
  ISRO Problem Statement 26174. The official public description is truncated
  after *"You are given a box that contains two smaller boxes of color red and
  yellow…"*, so the labelled activities above are **not** an undisclosed
  official ISRO sequence — do not present them as such.

### Tests

```powershell
backend\.venv\Scripts\python.exe -m pytest dataset\tests -q
```

Covers configuration validation (mirroring the backend camera defaults),
unique session creation, label slugging, `metadata.json` round-trips, the
`manifest.csv` format, directory layout, YOLO label parsing, coordinate/class
validation, the session-aware split, leakage detection, missing/malformed
annotation detection, the **activity dataset** (canonical vocabulary from
`experiment/experiment.json`, activity session creation, metadata + manifest,
activity directory layout), and the **training export** (validated
`data.yaml`, class histograms, ONNX + `.names` install). No camera or display
needed.

`overlay_smoke.py` is an **opt-in, interactive** camera check (not a pytest):
it applies the recorder overlay to mock frames and, with `--camera <index>`,
to a real webcam, and asserts the HUD pixels (band, status color, border) are
genuinely drawn.

```powershell
backend\.venv\Scripts\python.exe dataset\overlay_smoke.py --camera 0
```

## Roboflow everyday-objects set (Phase 4C+)

`roboflow/` is a **downloaded, pre-labelled** YOLOv8-format export
(`train/` + `valid/`, 15 everyday-object classes: Bag, Book, Bottle, Cell
Phone, Cup, Fork, Keys, Laptop, Paper, Pen, Spects, Spoon, Stairs, Wallet,
Watch). It is intentionally separate from the app's own `raw/` object set (a
webcam session of the experiment scene): two independent sources feeding the
same runtime detector via its famous `ONNX + .names` contract.

### Existing no-weights paths

You do **not** need a trained model to see detection run today:

- `DETECTION_BACKEND=mock` — deterministic `person 0.95 / red_box 0.91 /
  yellow_box 0.89`, no weights. See `backend/run_mock_demo.ps1`.
- `DETECTION_BACKEND=heuristic` — real pixels, model-free. See
  `backend/run_camera_demo.ps1`.

### Prepare the download (train/val/test + data.yaml)

The export has no `test/` split and a `data.yaml` with broken relative paths,
so we normalise it once into `roboflow/split/`:

```powershell
.\\.venv\\Scripts\\python.exe dataset\\scripts\\prepare_roboflow.py
# -> dataset/roboflow/split/{train,val,test}/{images,labels} + split/data.yaml
#    train=16052 val=1540 test=171  (a 10% holdout carved from `valid`)
```

This bridge (unlike `prepare_split.py`) works on the **flat** Roboflow layout
and normalises labels to **bounding-box rows only** — Roboflow sometimes
exports instance-segmentation polygons (class + N coordinate pairs) that
duplicate the box; those rows are dropped for detection training, matching
ultralytics box-only training. Nothing in the source is modified.

### Train (lightweight, small default run)

Ultralytics stays **optional** — it is only required on the training machine
(`dataset/requirements-train.txt`), never at runtime. Create a dedicated venv:

```powershell
python -m venv .venv-train
.venv-train\\Scripts\\pip install -r dataset\\requirements-train.txt
# quick verify run (3 epochs, yolov8n = ~6MB model):
.venv-train\\Scripts\\python.exe dataset\\scripts\\train_roboflow.py --epochs 3
# real run:
.venv-train\\Scripts\\python.exe dataset\\scripts\\train_roboflow.py --epochs 60 --imgsz 640
```

The script fails fast with a clear message if ultralytics is missing, and
prints where the trained `best.pt`/`best.onnx` land under `dataset/runs/`.

### Evaluate through the real runtime detector

The exported ONNX is scored with the **exact consumer the backend uses**
(`ai/detection/yolo_detector.YoloDetector`), so you can trust the result when
you switch to `DETECTION_BACKEND=yolo`:

```powershell
# 1. export best.pt -> ONNX (from .venv-train):
.venv-train\\Scripts\\yolo export model=dataset/runs/train/weights/best.pt format=onnx
# 2. evaluate on the test holdout (backend venv, no ultralytics):
.\\.venv\\Scripts\\python.exe dataset\\scripts\\evaluate_roboflow.py --onnx dataset/runs/train/weights/best.onnx
```

### Install + integrate (localhost, not committed)

```powershell
# writes models/detection/roboflow.onnx + roboflow.names (15 classes, taken
# from the roboflow data.yaml), leaving the app's own yolov8n.onnx/.names
# untouched:
.\\.venv\\Scripts\\python.exe dataset\\scripts\\install_detection_model.py `
    --onnx <best.onnx> --classes dataset\\roboflow\\split\\data.yaml --dest models\\detection\\roboflow.onnx
# run the backend on the everyday-objects model:
$env:DETECTION_ENABLED="true"; $env:DETECTION_BACKEND="yolo"
$env:DETECTION_MODEL_PATH="detection/roboflow.onnx"
.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000 --app-dir backend
```

See `models/detection/README.md` for the `ONNX + .names` runtime contract and
the honest limitation that a generic YOLO model does not recognise the Astra
`experiment_box`/`target_area` classes — those still need the app's own
trained model.
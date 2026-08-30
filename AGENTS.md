# AGENTS.md

Project conventions for AI coding agents working in this repository.

## Stack

- **Frontend:** React 19 + Vite + TypeScript + Tailwind CSS v4 (`frontend/`)
- **Backend:** Python 3 + FastAPI + Pydantic v2 (`backend/`)
- **No cloud services, no cloud TTS, no LLM-based validation.** All processing
  must stay local.

## Conventions

- Perception (`Detection`) is separate from decision-making (state machine).
  The state machine is the only authority on step validity — never an LLM.
- Experiment sequences are **data**: the canonical definition is
  `experiment/experiment.json` (the runtime default and the activity
  vocabulary source); `backend/experiments/*.json` are drop-in demo/legacy
  definitions. Never hardcode an experiment in code.
- Field naming mirrors across Python and TypeScript (camelCase JSON, e.g.
  `stepId`, `currentStepIndex`) so snapshots pass through without mapping.
- Keep new dependencies minimal. Install them before use and note them in the
  appropriate `requirements*.txt` / `package.json`.
- No code comments unless they explain *why*; keep them brief.

## Commands

### Backend (`backend/`, venv at `.venv`)

```powershell
.\.venv\Scripts\python.exe -m pytest        # run tests (incl. camera)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

The camera layer lives in `backend/camera/` (`capture.py`: `OpenCVCamera`,
`MockCamera`, `FrameReader`; `manager.py`: `CameraManager` + `CameraStatus`
`disconnected|connected|error`). Design rules:

- The manager owns a single background **daemon** capture thread; it encodes
  JPEGs in that thread and the MJPEG async generator only reads the latest
  snapshot — the event loop is never blocked by OpenCV.
- `threading.Lock` is non-reentrant: no*locked* method may call another
  *locked* method. Snapshot shared state via `_snapshot_locked()` under the
  lock; everything else calls `info()`/`is_running()`/`latest_jpeg()`.
- The camera never auto-starts; the dashboard drives it via
  `POST /api/camera/start|stop`, polls `GET /api/camera/status`, and mounts
  the live feed with `<img src="/api/camera/stream">`.
- Tests must never touch a physical device — inject
  `CameraSettings(mock=True, ...)` into `create_app(..., camera=...)`.
- Do not test the live MJPEG route by httpx `client.stream(...)` — it hangs on
  Python 3.14 (Starlette TestClient portal). Use the offline `503` contract +
  drive `camera_manager.mjpeg_frames()` directly
  (`backend/tests/test_camera.py`). A uvicorn smoke covers the real stream.

### Detection (Phase 3)

`ai/detection/` is the local object-detection layer (interface, mock, YOLO
ONNX); `backend/app/detection_service.py` runs it against the camera feed on
its own daemon thread and exposes `GET /api/detection/status` +
`GET /api/detections` (camelCase payloads: `class_name`, `confidence`,
`x1/y1/x2/y2`, `timestamp` epoch-ms, plus `frameWidth/frameHeight`). Rules:

- Design rules: never auto-download weights (manual drop into
  `models/detection/`, resolution via `resolve_weights_path`); never import
  `ai` while detection is disabled (inert `DetectionService`, no thread);
  missing YOLO weights / detector failures surface as an `error` in status —
  the app must never crash over detection.
- Mock detector is deterministic (`person 0.95`, `red_box 0.91`,
  `yellow_box 0.89`, boxes derived from frame size) so e2e/API tests are
  stable; `scene="empty"` yields no detections.
- `heuristic` detector (`DETECTION_BACKEND=heuristic`,
  `ai/detection/heuristic_detector.py`) is model-free and runs on real pixels:
  `person` from frame-to-frame motion, `red_box`/`yellow_box` from saturated
  HSV-hue blobs. Deterministic for synthetic input, imperfect on live scenes,
  and it deliberately **never** reports `experiment_box`/`target_area` — those
  honestly require a trained model.
- YoloDetector reuses `ai/pipeline/yolo.py` helpers (letterbox, postprocess,
  `resolve_weights_path`); a `.names` file next to the ONNX overrides classes.
- The DetectionService thread calls only `camera_manager.latest_capture()`
  (frames identified by frame id) — never locked methods, never the MJPEG
  generator; it must keep working when the camera is stopped (idle).
- Backend/ai venvs are separate: `backend/tests/test_detection.py` imports
  `ai` after `app.main` (which puts the repo root on `sys.path`);
  `ai/tests/test_detection.py` runs under `ai/.venv` (root inserted via
  `ai/conftest.py`).
- A generic pretrained YOLO does **not** recognise the Astra AI classes; keep
  that limitation honest in docs and status.

### Runtime activity perception (Phase 5C bridge)

`backend/app/activity_perception.py` is the seam that feeds the state machine
at runtime (same `Detection` shape the scripted feed always used). Rules:

- `load_active_experiment()` prefers the canonical
  `experiment/experiment.json` (override with the `EXPERIMENT_FILE` env var);
  `backend/experiments/*.json` is the legacy fallback. `StepDef`/`ExperimentDef`
  carry the canonical contract (optional fields) so legacy demo JSON still parses.
- Perception source selection: a provided `sim_script` always opts into
  `SimulatedPerception` (tests/back-compat); otherwise `ACTIVITY_BACKEND`
  (`live` default | `mock` | `sim`) picks `LiveActivityPerception`,
  `MockActivityPerception` or `SimulatedPerception`.
- `LiveActivityPerception` (DEFAULT) is the **camera-grounded** source. It
  polls `DetectionService.latest()` (honest object detections only — mock,
  yolo or heuristic) and emits a step Detection when the currently expected
  step's `expectedObjects` are all present on a fresh frame at/above
  `conf_threshold`. Rules:
  - Stale gate: detector disabled/errored or no inference within
    `ACTIVITY_STALE_MS` (camera stopped) ⇒ no emission — the experiment
    never advances or completes out of thin air.
  - Emission is edge-triggered per expected step (empty `expectedObjects`
    steps never fire; holding an object in view never repeats a step).
    Because only the expected step can emit, `live` is deliberately silent
    about repeated/out-of-sequence actions — that coverage is the mock's job.
  - `service.start()` calls `perception.reset()` when present; pass the
    session's `current_step_index` via `current_index` at wiring time.
- `MockActivityPerception` is a **mock** — deterministic and derived from the
  loaded experiment's own steps (correct sequence + a fixed rotation of
  planted mistakes: later-step OOS, repeat, low-confidence, unknown). It never
  claims to interpret camera frames; a real activity model plugs in at this
  same seam later. The object-detection overlay (`DetectionService`) stays a
  separate, honest sidebar.
- `ExperimentService.start(perception)` only needs an async `detections()`
  iterator — swap sources without touching decision-making.

### Dataset (Phase 4A)

`dataset/` is the **local-only** capture toolset (no upload, no cloud). The
recorder (`dataset/scripts/record_dataset.py`) reuses the production camera
config via `backend/camera/capture.py:CameraSettings` — it must never modify
the camera layer. Sessions land in `dataset/raw/<label>/session_<ts>_<rand>/`
(JPEG frames + `manifest.csv` + `metadata.json`). Rules:

- Shared logic lives in `dataset/dataset_tool.py` — intentionally **not**
  `scripts.*`, because `backend/scripts` is already a package; name collision
  breaks `import`.
- `DatasetConfig` defaults mirror the backend camera (index 0, 1280×720,
  30fps); validation lives in `__post_init__`; `interval` is seconds between
  saved frames.
- No training here (raw capture only). `frames/` + `annotations/` are filled
  by later phases.
- Tests: `backend\.venv\Scripts\python.exe -m pytest dataset\tests -q`
  (pure logic; never touches a camera or opens a window).

### Dataset annotation + split (Phase 4B)

`dataset/annotation/` is an **independent, dev-only** browser tool (no runtime
coupling to the BAS app, no new deps — stdlib `http.server`). It reads
`dataset/raw/`, writes YOLO label files into `dataset/annotations/` mirroring
raw paths (`frame_000001.jpg` → `frame_000001.txt`, `class cx cy w h`,
normalized 0–1), and never touches the originals. Rules:

- Classes are **config data**, not code: `dataset/annotation/classes.json`
  (edit it to add/rename classes; index = YOLO class id).
- Shared logic lives in `dataset/annotation/annotator.py` (parsing,
  validation, session grouping, split, leakage checks) — imported by
  `app.py`, `scripts/prepare_split.py`, `scripts/validate_dataset.py` and the
  tests. Never re-implement it.
- **Split is by recording *session*** (an image's directory under `raw/`), so
  one session can never appear in more than one of train/val/test (default
  70/20/10, `--seed`). The split CLI/validator stay consistent with
  `annotator.make_split` / `find_session_leakage`.
- Annotations with no boxes (blank label) are valid (negative/background
  frames); a **missing** label file for a split image is an error.
- Commands (backend venv, repo root): annotate
  `.\\.venv\\Scripts\\python.exe dataset\\annotation\\app.py`, split
  `dataset\\scripts\\prepare_split.py --root dataset`, validate
  `dataset\\scripts\\validate_dataset.py --root dataset`.

### Training bridge (Phase 4C)

`dataset/training_tool.py` + `dataset/scripts/export_training.py` translate
the validated split into an ultralytics `data.yaml`; `install_detection_model.py`
installs a trained ONNX + `.names` for the runtime. Rules:

- `make_data_yaml` reuses `annotator.validate_dataset` (missing labels are
  errors, blank labels fine, class-id range, session leakage) and requires
  non-empty train+val; `test` is omitted when empty. Raises `ValueError` (CLI
  exits 2) on anything untrainable.
- Ultralytics is **optional and never imported at runtime**
  (`dataset/requirements-train.txt`). The backend reads the exported ONNX via
  OpenCV DNN only.
- The `.names` file written next to the ONNX (from `classes.json`,
  index-aligned) is the trained-class contract with
  `ai/detection/yolo_detector.py` — never hand-edit a class list in code.
- Commands (backend venv, repo root): export
  `dataset\\scripts\\export_training.py --root dataset`, install
  `dataset\\scripts\\install_detection_model.py --onnx <exported>.onnx`. See
  `models/detection/README.md` for the full train → export → install → run loop.

### Activity dataset (Phase 5B)

`dataset/scripts/record_activity.py` records **activity** takes into
`dataset/activity/<ACTIVITY>/session_<ts>_<rand>/` (JPEG + `manifest.csv` +
`metadata.json`). Rules:

- **Activity names are data from the canonical `experiment/experiment.json`**
  (`activities` list) — the vocabulary is never duplicated in code or other
  files. `--activity` uses argparse `choices=load_activities()` so invalid
  names fail fast.
- Shared logic lives in `dataset/activity_tool.py` (pure, camera-free like
  `dataset_tool.py`): vocabulary loading, `ActivityConfig` (with
  `to_camera_settings()` reusing the backend camera layer), session
  creation, metadata, manifest. `record_activity.py` reuses the proven HUD
  helpers `_shade`/`_text` and `KEY_SPACE`/`KEY_ESC` from `record_dataset.py`.
- `metadata.json` schema `bas-activity-session/1`; `source` is `webcam` or
  `mock`. The recorder CLI + tests cover invalid-activity rejection.
- `record_dataset.py` (object feeder `raw/`) and `experiment/experiment.json`
  stay untouched — activity sessions never mix with object sessions.

### Frontend (`frontend/`)

```powershell
npm run dev              # dev server (port 5173, proxies /api & /ws to :8000)
npm run build            # tsc -b && vite build
npm run lint             # oxlint
npm run test:reducer     # state-machine parity test (Node type-stripping)
```

### AI / perception (`ai/`, venv at `ai/.venv`)

```powershell
.\.venv\Scripts\python.exe -m pytest                       # run tests (80)
.\.venv\Scripts\python.exe -m pipeline.cli --detector mock --source null   # headless demo
.\.venv\Scripts\python.exe -m pipeline.cli --detector mock                # live preview
.\.venv\Scripts\python.exe -m pipeline.cli --detector yolo                # needs models/yolo/*.onnx
.\.venv\Scripts\python.exe -m pipeline.cli --interaction --headless --print-detections   # hand⇄object event chain
```

The `ai/` package is independent of FastAPI by design. Change
`ai/pipeline/base.py:BaseDetector` semantics → update `ai/tests/`. Never
auto-download model weights; drop them into `models/yolo/` (ONNX) and
`models/pose/` (`hand_landmarker.task` for MediaPipe) manually.

`ai/pipeline/interaction/` produces only **perception observations**
(`HAND_NEAR_*`, `*_MOVED`, `*_PLACED`) — temporal spatial facts, never
activity/step-validity claims. Proximity alone must never emit `*_MOVED` /
`*_PLACED`; those require consecutive-frame motion and (for PLACED) settling
inside the `target_area`. `MediaPipeHandTracker` is lazy-imported (the
`mediapipe-tasks` wheel does not exist for Python 3.14); tests use
`MockHandTracker`. When changing interaction semantics, keep
`tests/test_interaction_tracker.py` and `tests/test_interaction_scene.py` in
agreement.

**Always run `npm run lint` and `npm run build` after frontend changes, and
`python -m pytest` after backend changes.** Run `ai` pytest after `ai/`
changes.

## Verify parity

The `STEP_MATCHED` / `OUT_OF_SEQUENCE` / `SKIPPED_STEP` / `REPEATED_STEP` /
`UNKNOWN_ACTIVITY` / `LOW_CONFIDENCE` classification is implemented twice —
TypeScript (`frontend/src/domain/reducer.ts`) and Python
(`backend/app/state_machine.py`). When changing behaviour, update **both** and
keep `npm run test:reducer` and `backend/tests/test_state_machine.py` in
agreement. Each classification event also carries a short `result` label
(`CORRECT` / `OUT_OF_SEQUENCE` / `SKIPPED` / `REPEATED` / `UNKNOWN` /
`LOW_CONFIDENCE`), derived from `kind` in both implementations. See
`docs/STATE_MACHINE.md` for the full transition table.
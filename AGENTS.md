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
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000   # plain dev; detection OFF by default
.\run_camera_demo.ps1                        # heuristic + live + demo experiment (detection ON)
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
- **Model roles are fixed and must never be swapped.** `yolov8n.onnx` (80 COCO
  classes) is the ONLY model allowed to be the general/primary detector.
  `experiment_custom.onnx` has 2 classes (`red_box`, `yellow_box`) and therefore
  cannot see a person — it is a *specialised* experiment detector usable only
  via `DETECTION_BACKEND=dual`. `YoloDetector._warn_if_narrow` logs a loud
  warning and `DetectorStatus.general_purpose=False` whenever a model with
  <10 classes is loaded; `start.ps1` prints the role in the startup banner.
- **Class vocabulary is the model's contract.** A `.names` file next to the
  ONNX (index-aligned, one per line) overrides the built-in
  `DEFAULT_CLASSES` placeholder. If it is missing, the 5-entry ASTRA list would
  be applied to an 80-class head and `keep &= class_ids < 5` would silently
  drop everything — the app would appear to "only see person" with no error.
  `YoloDetector._check_channel_match` raises `ValueError` on any
  `channels - 4 != len(classes)` mismatch on the first forward. Never "fix"
  that by editing a class list in code.
- `DetectionService._bootstrap` calls `detector.load()` **eagerly** before
  reading `status()`. Without it the banner reports the 5-entry placeholder
  and a null size — i.e. a different model than the one actually in use. A load
  failure must record `_last_error` and keep the service enabled so status
  still names the requested detector; never set `_enabled=False` there.
- `DETECTION_CONF_THRESHOLD` defaults to **0.25** (YOLOv8's own default). At
  0.50 the same real frames yield 15 detections (person+laptop only); at 0.25
  they yield 32 across 5 classes. A high threshold deletes objects, it does not
  make the detector stricter.
- `DETECTION_CV_THREADS` defaults to **8**, and `0` now means "leave OpenCV's
  auto selection alone". The old code called `setNumThreads(1)` on 0,
  contradicting its own config comment and pinning inference to one core:
  measured 666ms/forward at 1 thread vs 293ms at 8 on a 16-logical-CPU host.
  Do not re-add a forced single thread.
- Mock detector is deterministic (`person 0.95`, `red_box 0.91`,
  `yellow_box 0.89`, boxes derived from frame size) so e2e/API tests are
  stable; `scene="empty"` yields no detections.
- `heuristic` detector (`DETECTION_BACKEND=heuristic`,
  `ai/detection/heuristic_detector.py`) is model-free and runs on real pixels:
  `person` from frame-to-frame motion, `red_box`/`yellow_box` from saturated
  HSV-hue blobs. Deterministic for synthetic input, imperfect on live scenes,
  and it deliberately **never** reports `experiment_box`/`target_area` — those
  honestly require a trained model.
- `DetectionService` emits **two feeds**: `detections` (stable) and
  `rawDetections` (current-frame, debugging). A `TemporalTracker`
  (`backend/app/detection_tracker.py`) promotes a raw detection to stable only
  after `DETECTION_DEBOUNCE_FRAMES` (default 2) consecutive frames and
  EMA-smooths confidence+box (`DETECTION_EMA_ALPHA`, default 0.35). It never
  invents detections; disappearance still removes the object the same frame it
  vanishes (absence/down signals are never delayed). `DETECTION_CV_THREADS`
  (default 0 = auto) caps the OpenCV thread pool explicitly; on Windows the
  detector daemon thread gets a priority bump (Best-effort, never fatal).
- YoloDetector reuses `ai/pipeline/yolo.py` helpers (letterbox, postprocess,
  `resolve_weights_path`); a `.names` file next to the ONNX overrides classes.
- `DETECTION_BACKEND=dual` runs two independently configurable models
  (`DETECTION_GENERAL_MODEL_PATH`, `DETECTION_CUSTOM_MODEL_PATH`) and merges
  them with cross-model NMS. `DETECTION_MODEL_PATH` stays the single-model
  setting for `DETECTION_BACKEND=yolo`; never silently reuse it for both dual
  slots.
- The DetectionService thread calls only `camera_manager.latest_capture()`
  (frames identified by frame id) — never locked methods, never the MJPEG
  generator; it must keep working when the camera is stopped (idle).
- **AI rate is decoupled from camera FPS.** `DETECTION_FPS` (default 8, `0` =
  uncapped) caps inference in `_infer_once`; the camera keeps its own FPS. The
  thread always takes the **newest** frame — rate-skipped frames are dropped,
  never queued, so no backlog forms. `status()` adds `targetFps`/`actualFps`/
  `inferenceCount`/`skippedForRate`/`traceEnabled`. `actualFps` is a *cap*,
  not a guarantee: it equals the model rate when inference is slower.
- `DETECT_LOG_ENABLED` (default **false**) gates `ai/detection/detect_log.py`
  via `set_enabled()`; `postprocess_yolov8` wraps its whole per-candidate
  decode sweep in one `if`. Measured 23.8 -> 5.5 ms/frame. Verbose tracing
  costs real time — never leave it on in a normal run.
- Both shipped ONNX models are hard-fixed at 640x640; a smaller `input_size`
  fails with `outTotal == inpTotal` in the DNN reshape. Thread-priority bumps
  gave no measurable gain — do not re-add them. `yolov8n.onnx` is COCO-84
  (`person`, `bottle`); `experiment_custom.onnx` is the only source of
  `red_box`/`yellow_box`, so those need `DETECTION_BACKEND=dual` (~2x cost).
- Measured costs: camera JPEG 8.3ms, preprocess 4.6ms, postprocess 5.5ms,
  generic motion 11.3ms, but **one 640 forward ~203ms — inference is ~90% of
  the budget**. Optimise the number of forwards, not the surrounding Python.
  See `docs/PERFORMANCE_AND_UNATTENDED_REPORT.md`.
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
- `backend/experiments/heuristic_live_demo.json` is a drop-in demo whose
  `expectedObjects` use only the heuristic detector's real classes
  (`person`/`red_box`/`yellow_box`) so the **live** path can advance on actual
  frames (`EXPERIMENT_FILE=...` + `ACTIVITY_BACKEND=live`). The canonical
  `experiment/experiment.json` stays authoritative and is not modified.
- `MockActivityPerception` is a **mock** — deterministic and derived from the
  loaded experiment's own steps (correct sequence + a fixed rotation of
  planted mistakes: later-step OOS, repeat, low-confidence, unknown). It never
  claims to interpret camera frames; a real activity model plugs in at this
  same seam later. The object-detection overlay (`DetectionService`) stays a
  separate, honest sidebar.
- `ExperimentService.start(perception)` only needs an async `detections()`
  iterator — swap sources without touching decision-making.

### Unattended-object monitoring

`backend/app/attendance.py` (`AttendanceMonitor`) turns detections into
held/unattended object watches. Two chains, deliberately kept separate:

- **unknown** (`is_unknown`): the original `UNKNOWN_DETECTED -> POSSIBLY_HELD
  -> HELD -> RELEASED -> UNATTENDED` machine, frame-counted, requires an
  `HELD -> RELEASED` transition. Unchanged; `test_unknown_objects.py` guards it.
- **known** (`UNATTENDED_TRACKED_CLASSES`, e.g. `bottle`): proximity + wall
  clock. A placed-and-left object is tracked from its **first** detection, so
  never require `HELD`/`RELEASED`.

Rules:

- `AttendanceMonitor._reconcile` must feed **both** `unknownDetections` and the
  tracked known classes. Watching only unknown detections is the original bug:
  known objects were invisible, so nothing ever alerted.
- Containment is `_containment_score` = intersection-over-**object**-area
  ("how much of the object is in the container"), threshold
  `UNATTENDED_CONTAINMENT`. It must be a real intersection test; a loose
  inequality such as `y2 > box.y1` can never fire and looks implemented while
  doing nothing. `OBJECT_INSIDE_BOX` is an **event**, never a state.
- Unattended uses **wall clock** (`UNATTENDED_TIMEOUT_MS`), not frame counts.
  At ~1 AI FPS a 5-frame rule means 5 s, at 25 FPS it means 0.2 s.
- Person association is normalised bbox-centre proximity
  (`UNATTENDED_PROXIMITY`); hand/pose is not wired in, so "touch" is
  approximated by body proximity. Say so in docs.
- A stale feed must freeze state (`ACTIVITY_STALE_MS`) — never time out or
  resolve on a dead feed.
- Attendance needs a **UI** or the work is invisible: `useAttendance` already
  polls into context, and `CameraView` renders the containment/attendance panel.
  If you add a field the panel shows, add it to both `domain/attendance.ts` and
  `domain/detection.ts` or `tsc -b` fails.
- Known limitation, keep it honest: `GenericProposalDetector` is motion-only,
  so a **static unknown** object still disappears once the background adapts.
  Only known classes are covered. Do not paper over this.

### Astronaut safety monitoring (Phase 6)

`backend/app/safety/` is the **active core** (the box experiment is a decoupled
legacy demo). `SafetyService` pulls `detection_service.latest()`, runs the
`HazardEngine` (temporal confirmation + microgravity risk scoring from the
config-driven `hazards.json` KB), the `EmergencyManager` (rules backend:
absence/stillness/collision), the `SafetyMonitor` (NORMAL→OBSERVING→CAUTION→
WARNING→CRITICAL→EMERGENCY), `AlertManager` (dedup by root-cause `key`,
escalate-in-place, cooldown, ack) and the `IncidentLog` (evidence frame +
metadata + staged `escalation.json`). Rules:

- `backend/app/config.py`: `SAFETY_ENABLED` true by default;
  `EARTH_ESCALATION_ENABLED` true when unset; `MOCK_SCENE` (empty = `bas`);
  hazard/scene config in `hazards.json` is DATA, never code. One-frame hazards
  are capped at CAUTION until `SAFETY_PERSIST_FRAMES`; a **stale** feed
  (camera off / detector error) retains the last scene and never
  auto-resolves or auto-escalates — the monitor must never lie on a dead feed.
- Honest wording everywhere: "possible hazard / emergency candidate / risk
  assessment", never medical diagnoses; Earth escalation staged locally as
  `EARTH_ESCALATION_PACKAGE_READY` (nothing is transmitted). Confirmed
  CRITICAL, crew-near WARNING, and confirmed emergencies open incidents.
- `MockDetector(scene=...)` scenes live in `ai/detection/mock_detector.py`:
  `bas`, `empty`, `space_station` (`person` + drifting `floating_tool` +
  `loose_cable`), `safety_sequence` (same, then `person` clears →
  `ASTRONAUT_UNOBSERVED`/`ASTRONAUT_DOWN`). `MOCK_SCENE` flows
  via `DetectionService.…scene=config.MOCK_SCENE or None`. Generic YOLO does
  not learn these classes; keep that honest in docs.
- Backend tests: `backend/tests/test_safety.py` (19 tests, `StubDetection` +
  `build_safety_client`; camera-free). `backend/tests/test_api.py` consumes the
  extra `{"type":"safety"}` WS message on connect.
- Frontend: `domain/safety.ts` (snapshot/alert/incident/station mirrors),
  `hooks/useSafety.ts` (1 s polling + `onWsMessage` WS ingest), new views in
  `views/` under a safety-first nav (`Mission`, `Camera`, `Hazards`, `Crew`,
  `Alerts`, `Station`, `Earth`, `Logs`; legacy box demo = `Demo` tab). Keep
  `npm run test:reducer`, `lint`, `build` green after changes.

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
  70/20/10, `--seed`). Exact duplicate images shared across splits are errors;
  flat layouts are warnings in the validator and rejected by the training
  export. The split CLI/validator stay consistent with
  `annotator.make_split` / `find_session_leakage` / `find_duplicate_images`.
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
  errors, blank labels fine, class-id range, session leakage, exact cross-split
  duplicates) and requires provable recording-session directories plus non-empty
  train+val; `test` is omitted when empty. Raises `ValueError` (CLI exits 2) on
  anything untrainable.
- Ultralytics is **optional and never imported at runtime**
  (`dataset/requirements-train.txt`). The backend reads the exported ONNX via
  OpenCV DNN only.
- Current measured state of the detector and the training data (read before
  proposing a fine-tune or promoting a model): `docs/YOLO_FINE_TUNING_AUDIT.md`
  (stack + defects), `docs/YOLO_DATASET_REPORT.md` (class coverage, duplicates,
  leakage), `docs/YOLO_FINE_TUNING_RESULTS.md` (evaluation numbers, readiness
  gate). Known blockers: `yellow_box` has zero boxes, `experiment_train` is a
  frame-level split of one clip with no test split, and a generic YOLO does not
  learn the ASTRA classes.
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
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
- Experiment sequences are **data** (JSON in `backend/experiments/`), not
  application code.
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
- YoloDetector reuses `ai/pipeline/yolo.py` helpers (letterbox, postprocess,
  `resolve_weights_path`); a `.names` file next to the ONNX overrides classes.
- The DetectionService thread calls only `camera_manager.latest_capture()`
  (frames identified by frame id) — never locked methods, never the MJPEG
  generator; it must keep working when the camera is stopped (idle).
- Backend/ai venvs are separate: `backend/tests/test_detection.py` imports
  `ai` after `app.main` (which puts the repo root on `sys.path`);
  `ai/tests/test_detection.py` runs under `ai/.venv` (root inserted via
  `ai/conftest.py`).
- A generic pretrained YOLO does **not** recognise the BAS-AI classes; keep
  that limitation honest in docs and status.

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
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

### Frontend (`frontend/`)

```powershell
npm run dev              # dev server (port 5173, proxies /api & /ws to :8000)
npm run build            # tsc -b && vite build
npm run lint             # oxlint
npm run test:reducer     # state-machine parity test (Node type-stripping)
```

### AI / perception (`ai/`, venv at `ai/.venv`)

```powershell
.\.venv\Scripts\python.exe -m pytest                       # run tests (69)
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
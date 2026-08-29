# BAS-AI — SIH 2026 PS 26174

Offline AI-based **Human Activity Recognition** for on-board experiment
assistance on Bharatiya Antariksh Station (BAS). A fixed camera watches the
operator, the system recognises predefined experiment activities against a
**configurable** sequence, validates their order, detects errors, and drives a
live monitoring dashboard — fully offline.

This repository contains the **software prototype foundation**: a React
dashboard, a FastAPI backend, WebSocket streaming, a configurable experiment
simulator, a local webcam capture layer (Phase 2) that streams MJPEG to the
dashboard, and an OpenCV perception pipeline with both mock and YOLO
detectors, plus a hand/object interaction module (Phase 4) that turns
detections + hand landmarks into temporal `HAND_NEAR`/`MOVED`/`PLACED`
observations. Real trained detection enters by dropping an ONNX model into
`models/yolo/`, and real hand tracking by dropping `hand_landmarker.task` into
`models/pose/` (MediaPipe Tasks). **No cloud services, no cloud TTS, no LLM
validation.**

## Monorepo layout

```
frontend/   React + Vite + Tailwind dashboard
backend/    FastAPI server (REST + WebSocket + state machine + simulator)
ai/         OpenCV perception pipeline (mock AND YOLO detectors + webcam) — no FastAPI deps
            + hand/object interaction module (hand.py + pipeline/interaction/)
dataset/    local-only capture tooling for a custom training dataset (Phase 4A)
models/     model weights (git-ignored, never auto-downloaded)
data/       runtime data: recordings/ and logs/ (git-ignored)
docs/       architecture and design notes
```

## Architecture in one breath

```
Webcam → OpenCV (backend/camera) ──MJPEG──► React dashboard (live feed)
Simulator (scripted detections)      — real: ai/pipeline (cam → detector) in later phases
   │  Detection {activity, confidence, ts}
   ▼
Experiment state machine (backend)       — the ONLY authority on step validity
   │  classified Events
   ▼
WebSocket (/ws) ──state snapshots──► React dashboard (real-time updates)
REST           ──start/stop/status/logs/camera
```

**Perception asks "what is happening?"; the state machine asks "is it valid
now?".** They never mix.

## Setup

Requirements: Node ≥ 22, Python ≥ 3.12.

### Backend

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate            # Windows (PowerShell)
source .venv/bin/activate           # macOS / Linux
pip install -r requirements-dev.txt
```

### AI / perception

```bash
cd ai
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-dev.txt
```

### Frontend

```bash
cd frontend
npm install
```

## How to run — backend

```bash
cd backend
.\.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

API docs at http://localhost:8000/docs. Quick check:
`Invoke-RestMethod http://localhost:8000/api/health`.

## How the camera works (Phase 2)

Dashboard shows a real local webcam feed. The flow is fully offline:

```
webcam (index 0) → cv2.VideoCapture → CameraManager (background thread)
   → latest frame encoded as JPEG → MJPEG multipart stream → <img> in React
```

The **Camera** panel on the dashboard shows a status indicator
(`CAMERA CONNECTED` / `CAMERA DISCONNECTED` / `CAMERA ERROR`) plus
**Start camera** / **Stop camera** buttons. The camera starts *off* — press
Start to begin. Controls are disabled in *Local simulator* mode (the camera
lives in the backend).

Camera endpoints (`backend/app/main.py`, logic in `backend/camera/`):

| Endpoint | Purpose |
| --- | --- |
| `GET  /api/camera/status`   | status, source, resolution, frame count, error |
| `POST /api/camera/start`    | open device + start capture (idempotent) |
| `POST /api/camera/stop`     | stop capture + release device (idempotent) |
| `GET  /api/camera/stream`   | MJPEG `multipart/x-mixed-replace`; `503` when not streaming |
| `GET  /api/camera/snapshot` | single JPEG frame (`503` when not streaming) |

Configuration is env-overridable (`backend/app/config.py`):

```bash
$env:CAMERA_INDEX="0"; $env:CAMERA_WIDTH="1280"; $env:CAMERA_HEIGHT="720"
$env:CAMERA_FPS="30";      $env:CAMERA_MOCK="false"   # mock feed for camera-free dev/kiosks
$env:CAMERA_JPEG_QUALITY="70"
```

**Mock camera mode** (`CAMERA_MOCK=true`): the same code path drives a
synthetic animated frame so the whole dashboard (stream, status, controls)
works with no webcam at all — used by the test suite too.

## How object detection works (Phase 3)

Local, offline, **optional**. On top of the camera feed, the backend runs a
detector thread that classifies each new frame and delivers the boxes over
REST; the dashboard draws a "Detected Objects" panel and live bounding-box
overlay on the video feed. Enabling it never changes the camera/MJPEG path —
with detection off the app behaves exactly as in Phase 2.

```
CameraManager (capture thread)──latest_capture()──► DetectionService (daemon thread)
   └─ MJPEG ─► dashboard <img>                           └─ ai/detection/ BaseDetector
                                                              mock  → deterministic person/red_box/yellow_box
                                                              yolo  → YOLOv8 ONNX (models/detection/)
   REST ── GET /api/detection/status ──► dashboard panel + overlays
                 GET /api/detections
```

Enable by restarting the backend with env vars (`backend/app/config.py`):

```bash
$env:DETECTION_ENABLED="true"
$env:DETECTION_BACKEND="mock"                # mock (no weights) or yolo
$env:DETECTION_MODEL_PATH="detection/yolov8n.onnx"   # default; see models/detection/README.md
$env:DETECTION_CONF_THRESHOLD="0.5"
$env:DETECTION_POLL_MS="100"
```

- **`mock`** — no weights, ready to demo: deterministic `person 0.95` /
  `red_box 0.91` / `yellow_box 0.89` boxes derived from the frame size.
- **`yolo`** — runs a YOLOv8 ONNX model via `cv2.dnn` (CPU, CUDA-capable).
  Missing weights → a *clear error* in `/api/detection/status`
  (`modelLoaded: false` + message) — **never a crash, never a download**.
  ⚠️ A generic pretrained YOLO does **not** recognise
  `experiment_box`/`red_box`/`yellow_box`/`target_area`; a custom-trained
  5-class model (or a `.names` file) is required for real detection — see
  `models/detection/README.md`.

Endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/detection/status` | enabled, detector type, model loaded, inference status, last inference, count, error |
| `GET /api/detections` | latest structured detections + source frame size (`503`-free; empty when idle/disabled) |

The **Object Detection** dashboard panel shows detector/model/inference state
and the live object list; boxes are drawn on the live feed using percentages
of the reported frame size. With detection disabled the panel shows an honest
"detection off" state and how to enable it.

## How to collect a custom dataset (Phase 4A)

No training yet — this phase captures the footage a future custom model will
be trained on. The recorder (`dataset/scripts/record_dataset.py`) reuses the
**same camera configuration** as the backend and stores sessions **locally**
(no upload anywhere):

```powershell
.\.venv\Scripts\python.exe dataset\scripts\record_dataset.py --label PICK_RED_BOX --interval 0.5
```

Inside the preview window: **SPACE** starts/stops recording, **Q**/ESC quits.
Sessions land in `dataset/raw/<label>/session_<ts>_<rand>/` (JPEG frames +
`manifest.csv` + `metadata.json`). Labels are slugified (`PICK RED BOX` →
`pick_red_box`). See `dataset/README.md` for flags, guidance, and tests.

**Testing the stream** (backend running):

```bash
curl http://localhost:8000/api/camera/snapshot -o frame.jpg -L   # single frame
# browser: http://localhost:8000/api/camera/stream (MJPEG, no JS needed)
```

**Troubleshooting**

- `CAMERA ERROR` after Start: the device at `camera_index` could not be
  opened — check it is plugged in and not already claimed by another app.
- The feed freezes/skips: low-end cameras drop frames; lower `CAMERA_WIDTH` /
  `CAMERA_HEIGHT` / `CAMERA_FPS` or raise `CAMERA_JPEG_QUALITY` balancing
  quality vs. bandwidth.
- No camera hardware at all: set `CAMERA_MOCK=true` and the mock feed drives
  the same UI.

## How to run — frontend

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` and `/ws` to `:8000`.

## How to run — tests

```bash
# backend (state machine + REST + WebSocket)
cd backend && python -m pytest

# frontend (state machine parity with backend)
cd frontend && npm run test:reducer

# frontend static checks / build
cd frontend && npm run lint && npm run build

# ai (perception pipeline, mock + yolo + webcam + hand interaction)
cd ai && python -m pytest

# dataset (session/config logic, no camera needed)
cd .. && backend\.venv\Scripts\python.exe -m pytest dataset\tests
```

## How to run — perception preview (Phase 3+)

```bash
cd ai
.\.venv\Scripts\activate
python -m pipeline.cli --detector mock               # live webcam preview window
python -m pipeline.cli --detector mock --source null # synthetic frames, no camera
python -m pipeline.cli --detector mock --headless --print-detections   # JSON lines
python -m pipeline.cli --interaction --headless --print-detections     # hand⇄object event chain
```

`--detector yolo` runs `ai/pipeline/yolo.py` (YOLOv8 ONNX via `cv2.dnn`) once
an exported model sits in `models/yolo/` — nothing is downloaded
automatically. See `ai/README.md` for the detector interface, the interaction
module, and the `{class_name, confidence, bounding_box, timestamp}` JSON
contract.

## How simulation works

1. Press **Start experiment** (Source: `Backend · FastAPI`).
2. `POST /api/experiment/start` launches `SimulatedPerception`
   (`backend/app/simulator.py`) — an async stream of scripted `Detection`s
   designed to exercise every outcome:
   - correct steps (`STEP_MATCHED`)
   - out-of-sequence step (`picks YELLOW when RED was expected`)
   - skipped-step advisory
   - repeated step
   - unknown activity
   - low-confidence detection
3. Each detection flows into the state machine
   (`backend/app/state_machine.py`), which produces classified `Event`s and a
   `state` snapshot.
4. Snapshots and events are pushed over `/ws` — the dashboard updates in real
   time without polling.

Switch the header source to **Local simulator** to run the same scripted
timeline entirely in the browser (no backend needed).

### Configuring the experiment

The sequence is JSON in `backend/experiments/` (active = first in sorted
order). The same definition is bundled into the frontend as an offline
fallback (`frontend/src/domain/experiment.ts`). Schema and notes:
`docs/ARCHITECTURE.md`. State machine semantics, transition table, and test
coverage: `docs/STATE_MACHINE.md`.

## Project rules

- Reliability > fancy UI.
- Perception is separate from decision-making.
- No LLM as the sequence validator.
- Offline-first everywhere.
- Minimal dependencies; clean modular code.
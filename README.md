# Astra AI — SIH 2026 PS 26174

Local-first **Astronaut Safety & Hazard Monitoring** for on-board experiments on
Bharatiya Antariksh Station (BAS), plus the original human-activity-recognition
experiment assistant as a decoupled legacy demo. A fixed camera watches the
operator; the system detects objects, classifies hazards from a **config-driven
knowledge base**, scores risk under the configured environment, drives a safety
monitor (NORMAL → … → EMERGENCY), raises de-duplicated alerts, records
incidents with evidence, and stages local-only Earth-escalation packages —
fully offline, no cloud, no LLM in the loop.

This repository contains the **software prototype foundation**: a React
dashboard, a FastAPI backend, WebSocket streaming, a configurable experiment
simulator, a local webcam capture layer (Phase 2) that streams MJPEG to the
dashboard, an OpenCV perception pipeline with mock, heuristic and YOLO
detectors, plus a hand/object interaction module (Phase 4). Real trained
detection enters by dropping an ONNX model into `models/yolo/` (and real hand
tracking by dropping `hand_landmarker.task` into `models/pose/` — MediaPipe
Tasks). **No cloud services, no cloud TTS, no LLM validation.**

## Monorepo layout

```
frontend/   React + Vite + Tailwind dashboard
backend/    FastAPI server (REST + WebSocket + state machine + perception stage)
ai/         OpenCV perception pipeline (mock AND YOLO detectors + webcam) — no FastAPI deps
            + hand/object interaction module (hand.py + pipeline/interaction/)
dataset/    local-only capture tooling for a custom training dataset (Phase 4A)
experiment/ canonical machine-readable experiment definition (experiment.json)
models/     model weights (git-ignored, never auto-downloaded)
data/       runtime data: recordings/ and logs/ (git-ignored)
docs/       architecture and design notes
```

## Architecture in one breath

```
Webcam → OpenCV (backend/camera) ──MJPEG──► React dashboard (live feed)
Perception stage (activity detections)      — live (default, camera-grounded:
   │  Detection {activity, confidence, ts}     expected step's objects visible)
   ▼                                         — mock-activity (demo feed)
                                             — simulated (scripted legacy feed)
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

## Quick Start

Once the [Setup](#setup) steps are done (backend venv + frontend `node_modules`),
start the **entire prototype with one command** from the project root:

```powershell
.\start.ps1
```

The script:

- verifies `backend/.venv` and `frontend/node_modules` exist,
- fails fast with a clear message if ports `8000` or `5173` are already in use,
- starts the **FastAPI backend** on `http://localhost:8000` with object
  detection **enabled in mock mode** (`DETECTION_ENABLED=true`,
  `DETECTION_BACKEND=mock` — deterministic `person / red_box / yellow_box`,
  no webcam or model weights required),
- starts the **React/Vite frontend** on `http://localhost:5173`,
- waits for both to be ready, then prints status, and
- on `Ctrl+C` (or closing the window) stops both child processes.

| Service | URL |
| --- | --- |
| Dashboard (frontend) | http://localhost:5173 |
| API / OpenAPI docs | http://localhost:8000/docs |
| Health check | http://localhost:8000/api/health |
| Detection status | http://localhost:8000/api/detection/status |

Runtime logs land in `.startup_logs/` (`backend.log`, `frontend.log`).

> Detection uses the **mock** backend for now because the real Roboflow-trained
> model is not integrated yet — see `models/detection/README.md` and the
> dataset README for the future `yolo` backend.

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

## How to annotate, split and validate the dataset (Phase 4B)

The annotation tool is a **dev-only, local-only** browser app (stdlib Python
server, no new dependencies, independent of the BAS runtime):

```powershell
# 1. Annotate: opens http://127.0.0.1:8700 — drag boxes, pick a class,
#    then S saves a YOLO label into dataset/annotations/ (N/P/D/C/Q = next,
#    prev, delete, clear, quit; class keys 0-4).
.\.venv\Scripts\python.exe dataset\annotation\app.py

# 2. Validate the source labels.
.\.venv\Scripts\python.exe dataset\scripts\validate_dataset.py --root dataset

# 3. Split by recording session (80/20/10) — a session is never divided.
.\.venv\Scripts\python.exe dataset\scripts\prepare_split.py --root dataset

# 4. Validate the split (labels present, YOLO-legal, no session leakage).
.\.venv\Scripts\python.exe dataset\scripts\validate_dataset.py --root dataset
```

Classes are config data in `dataset/annotation/classes.json`.

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

# dataset (capture + annotation/split/validation logic, no camera needed)
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

## How astronaut safety monitoring works (Phase 6)

The **new core** of the app. The safety monitor runs beside the legacy
experiment pipeline and owns the active risk assessment:

```
Camera → DetectionService (mock / heuristic / yolo) ──► HazardEngine
   ● temporal confirmation (a 1-frame blip never alarms)        │
   ● hazard class ↔ knowledge base (backend/app/safety/hazards.json)
   ● microgravity-aware risk score (ENVIRONMENT_MODE, configured)
                                                               ▼
                                                     SceneAssessment
                                                               │
                   ┌───────────────┬───────────────────────────┤
                   ▼               ▼                           ▼
             SafetyMonitor    EmergencyManager           AlertManager
   NORMAL→OBSERVING→CAUTION   rules backend (absence,   de-duplicated by
   →WARNING→CRITICAL→EMERG      stillness, collision)    root cause, escalate
                   │               │                     in place, cooldown
                   └───────────────┴───────────────────────────┤
                                                               ▼
        IncidentLog ── evidence frame + metadata ──► Earth-escalation package
                                                       (locally staged only)
```

Flow per cycle (`SafetyService.step()`): pull `detection_service.latest()`
→ `HazardEngine.assess()` → `EmergencyManager.update()` → `SafetyMonitor.update()`
→ alert reconcile → incidents/evidence/escalation → WS snapshot broadcast.

**Honest constraints** (nothing is ever faked):

- Missing/failed YOLO weights → status shows `AI ENGINE ERROR` with the
  reason; the monitor never crashes. Detection disabled or camera stopped
  → scene goes *stale* (last known state retained); **a dead feed never
  auto-resolves or auto-escalates**.
- The system reports "possible hazard / risk assessment / emergency
  candidate" — never a medical diagnosis. Robot/crew wording is used
  deliberately (e.g. `POSSIBLE_INJURY`).
- Earth escalation is **staged locally** as `escalation.json`
  (`EARTH_ESCALATION_PACKAGE_READY`); nothing is transmitted. `EARTH_ESCALATION_
  ENABLED=true` + `EARTH_ESCALATION_MIN_LEVEL=CRITICAL` control staging.
- Confirmed **CRITICAL** hazards, confirmed **WARNING** hazards* near the
  astronaut, and confirmed emergencies open an incident with evidence:
  `data/incidents/<id>/{event.json, frame_<ts>.jpg, metadata.json, escalation.json}`.
  *a WARNING far from the astronaut alerts but does not open an incident.

Config (`backend/app/config.py`, env-overridable):

| Variable | Default | Meaning |
| --- | --- | --- |
| `SAFETY_ENABLED` | `true` | autostart the monitor on boot |
| `ENVIRONMENT_MODE` | `microgravity` | operational environment for risk scoring |
| `MOCK_SCENE` | *(empty = `bas`)* | mock-detector scene: `bas` / `empty` / `space_station` / `safety_sequence` |
| `EARTH_ESCALATION_ENABLED` | `true` | stage escalation packages for qualifying incidents |
| `EARTH_ESCALATION_MIN_LEVEL` | `CRITICAL` | minimum incident severity to stage |
| `EMERGENCY_BACKEND` | `rules` | absence/stillness/collision rules backend |
| `ALERT_COOLDOWN_MS` | `15000` | re-raise cooldown for a resolved root cause |
| `SAFETY_POLL_MS` / `SAFETY_PERSIST_FRAMES` / `SAFETY_RESOLVE_FRAMES` / `SAFETY_STALE_MS` | `500` / `2` / `2` / `5000` | monitor loop & temporal gates |

Safety REST endpoints (see `backend/app/main.py` for the full list):

| Endpoint | Purpose |
| --- | --- |
| `GET /api/safety/status` | monitor + pipeline health (`mission_state`, `tick`, counts) |
| `GET /api/safety/snapshot` | mission state + per-object assessments + emergency |
| `POST /api/safety/start` \| `stop` | control the monitor loop |
| `GET /api/safety/alerts` | active + history alerts |
| `POST /api/safety/alerts/{id}/ack` | acknowledge an alert |
| `GET /api/safety/incidents` (+ `/api/safety/incidents/{id}`) | incident history + detail |
| `GET /api/safety/station` | Mission-Control / space-station console feed |
| `GET /api/safety/events` | safety event log |

The dashboard exposes everything through the new nav (Mission, Camera,
Hazards, Crew, Alerts, Station, Earth, Logs) plus a "Demo" tab for the legacy
box experiment. WebSocket `/ws` now also pushes `{"type":"safety"}` snapshots
and `{"type":"safety_event"}` events.

One command, no webcam or model weights — mock camera + mock detector playing
the `space_station` scene that yields a genuine `floating_tool` hazard ladder:

```powershell
.\backend\run_mock_demo.ps1
```

Full architecture, tests and migration notes: `docs/SAFETY_SYSTEM.md`.

## How the activity feed works

> The activity feed below is the **legacy experiment demo** (retained
> decoupled). The safety monitor above is the active core.

1. Press **Start experiment** (Source: `Backend · FastAPI`).
2. `POST /api/experiment/start` launches the configured perception source:
   - **live** (default, `ACTIVITY_BACKEND=live`):
     `LiveActivityPerception` (`backend/app/activity_perception.py`) — the
     **camera-grounded** source. It watches the object-detection service
     (`GET /api/detections`) and emits a step only when the currently expected
     step's `expectedObjects` are all visible on a fresh frame (Detectors:
     `mock` for demos, `heuristic` for model-free real color/motion, `yolo`
     once your model is trained). Camera off or no fresh frame -> it waits,
     honestly. The experiment never completes out of thin air.
   - **mock-activity** (`ACTIVITY_BACKEND=mock`): `MockActivityPerception` —
     a deterministic feed **derived from the loaded experiment definition
     itself** (`experiment/experiment.json`): the correct steps plus a fixed
     rotation of planted mistakes so a run exercises every outcome:
     - correct steps (`STEP_MATCHED`)
     - out-of-sequence step (picks a later step early)
     - skipped-step advisory
     - repeated step
     - unknown activity
     - low-confidence detection
   - **simulated** (`ACTIVITY_BACKEND=sim`): the original scripted feed
     (`backend/app/simulator.py`) — kept for tests and backwards compatibility.
3. Each detection flows into the state machine
   (`backend/app/state_machine.py`), which produces classified `Event`s and a
   `state` snapshot.
4. Snapshots and events are pushed over `/ws` — the dashboard updates in real
   time without polling. `/api/health` reports the live source name.

Switch the header source to **Local simulator** to run a scripted timeline
entirely in the browser (no backend needed).

> The camera-grounded feed only speaks when it actually sees the expected
> objects — with the model-free `heuristic` detector that means `person`
> (motion), `red_box`/`yellow_box` (colour). Seeing the `experiment_box` or
> `target_area` honestly requires a trained YOLO model (Phase 4C pipeline) —
> until then the experiment waits at those steps rather than guessing.

### Configuring the experiment

The canonical sequence is `experiment/experiment.json` (runtime default and
the single source of the activity vocabulary). `backend/experiments/*.json`
are drop-in legacy definitions. `EXPERIMENT_FILE=<path>` forces a specific
file. The frontend bundle ships a copy as an offline fallback
(`frontend/src/domain/experiment.ts`); when the backend is live the canonical
definition is served via `/api/experiment`. Schema and notes:
`docs/ARCHITECTURE.md`. State machine semantics, transition table, and test
coverage: `docs/STATE_MACHINE.md`.

## Project rules

- Reliability > fancy UI.
- Perception is separate from decision-making.
- No LLM as the sequence validator.
- Offline-first everywhere.
- Minimal dependencies; clean modular code
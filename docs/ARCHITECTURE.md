# Architecture

## System diagram

```
                     ┌────────────────────────────────────────────┐
                     │                frontend/                   │
                     │   React + Vite + Tailwind dashboard        │
                     │                                            │
                     │  Live feed · steps · confidence · log      │
                     └──────▲──────────────▲──────────────────────┘
                            │ WS snapshot  │ REST (start/stop)
                            │              │
                     ┌──────┴──────────────┴──────────────────────┐
                     │                backend/                     │
                     │              FastAPI (:8000)                │
                     │                                            │
│   /ws ── ConnectionManager ──► broadcast   │
                     │              │       ▲                     │
                     │              ▼       │ events + state      │
                     │   ExperimentService · ExperimentSession    │
                     │              ▲   (classification only)     │
                     │              │ Detection                   │
│   Perception stage   (pluggable)           │
                      │   live (default, camera-grounded) │         │
                      │   mock-activity (demo) · sim (legacy)       │
                      └────────────────────────────────────────────┘
                              ▲
              camera → object detection → live activity bridge
```

## Perception vs. decision-making

The core design rule (enforced in both backend and frontend):

- **Perception** asks *"what action is happening?"* and emits a `Detection`
  (`activity`, `confidence`, `ts`).
- **Decision-making** is the *experiment state machine*, which asks *"is this
  action valid at the current step?"* and emits classified `Event`s.

Every perception source is interchangeable because all of them produce the
exact same `Detection` shape. The state machine, WebSocket protocol and
dashboard never know (or care) which one is live.

## Configurable experiment definitions

The canonical definition is `experiment/experiment.json` — the runtime default
(loaded by `load_active_experiment()`) and the single source of the activity
vocabulary (recorder CLIs, tests). `backend/experiments/*.json` are drop-in
demo/legacy definitions loaded only when the canonical file is absent.
`EXPERIMENT_FILE=<path>` forces a specific file. Schema (canonical contract,
all fields optional for back-compat with the demo JSON):

```json
{
  "id": "bas-box-handling-01",
  "name": "BAS Box Handling Experiment",
  "activities": ["APPROACH", "OPEN_BOX", "PICK_RED", "PLACE_RED", "PICK_YELLOW", "PLACE_YELLOW", "COMPLETE"],
  "steps": [
    { "id": "step1", "order": 1, "activity": "APPROACH", "label": "Astronaut approaches the experiment area",
      "description": "…", "expectedObjects": ["person"] }
  ]
}
```

The frontend bundle ships a copy as a fallback
(`frontend/src/domain/experiment.ts`) for offline/local mode; when the backend
is live the canonical definition comes over `/api/experiment`.

## WebSocket protocol (server → client)

| type | data | purpose |
|------|------|---------|
| `state` | full `ExperimentState` snapshot | authoritative dashboard state; sent after every mutation and on connect |
| `event` | a classified `BasEvent` | timestamped log line |
| `detection` | a raw `Detection` | live perception feed (confidence display, future use) |

Client → server: `{"type":"ping"}` → `{"type":"pong"}`.

`state` snapshots are idempotent and self-describing, so the dashboard
rehydrates safely across reconnects.

## REST API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | liveness + active source + clients |
| GET | `/api/experiment` | definition + current state |
| GET | `/api/experiment/status` | current state snapshot |
| POST | `/api/experiment/start` | start the experiment (launches perception) |
| POST | `/api/experiment/stop` | stop and end recording |
| GET | `/api/logs` | historical event list |

## Event model

One vocabulary shared by Python (`backend/app/schemas.py`) and the browser
(`frontend/src/domain/types.ts`):

`STEP_MATCHED`, `OUT_OF_SEQUENCE`, `SKIPPED_STEP`, `REPEATED_STEP`,
`UNKNOWN_ACTIVITY`, `LOW_CONFIDENCE` plus lifecycle events
`EXPERIMENT_STARTED/STOPPED/COMPLETED`, `RECORDING_STARTED/STOPPED`.

Severity colouring: `ok` (green), `error` (rose), `warn` (amber), `info`.

## Frontend modes

- **Backend · FastAPI** (default): streams `state` snapshots over `/ws`
  (proxied by Vite to `:8000`); buttons call the REST API. The backend is the
  single authority.
- **Local simulator**: fully client-side replay of the scripted detections
  through the in-app reducer — used to demo the UI without a server.

## Perception backends (Phase 5C bridge)

`ExperimentService` consumes any object exposing an async `detections()`
iterator.

- **`interaction`** (default, `ACTIVITY_BACKEND=interaction`):
  `backend/app/interaction_perception.py` — event-grounded. Visibility is not an
  action: a box sitting in frame proves nothing about a pick or a place. This
  source feeds the real `ai.pipeline.interaction.InteractionTracker` (object
  tracks, motion, settling) and emits a step only when its `expectedEvents`
  (`PRESENT` / `MOVED` / `PLACED`) are satisfied by counted episodes. It is the
  only source that can tell a PICK from a pass-by, and the one that drives
  `WRONG_OBJECT` / `WRONG_SEQUENCE`.
  - Evidence is edge-triggered and **consumed one episode at a time**, so
    holding an object in view never re-fires a step and a step's confirmation
    window cannot swallow the next step's motion. Terminal (`fresh: false`)
    steps are latched so they are offered exactly once.
  - `target_area` is **configuration** (`ACTIVITY_TARGET_AREA`, normalized
    `x1,y1,x2,y2`), not a detection: no shipped model can see fixed station
    hardware. Unset means the run reports `placedGrounded: false` and `PLACED`
    is never claimed, rather than accepting any set-down object.
  - No hand-landmark model is installed, so `HAND_NEAR_*` never fires and a
    PICK is proven by object motion only.
- **`live`** (`ACTIVITY_BACKEND=live`): camera-grounded, presence-only.
  `LiveActivityPerception` polls `DetectionService.latest()` and emits the
  expected step's activity when every `expectedObjects` entry is present on a
  fresh frame above threshold. Edge-triggered per step; stale/disabled/frozen
  feeds emit nothing. A step with empty `expectedObjects` never fires. Because
  only the expected step can emit, it is silent about repeats/out-of-sequence,
  and it cannot ground a step on a class no detector emits.
- **`mock-activity`** (`ACTIVITY_BACKEND=mock`): deterministic, data driven
  from the loaded experiment — correct steps plus a fixed rotation of planted
  mistakes (later-step OOS, repeat, low-confidence, unknown) so a full run
  exercises every classification outcome. It is a mock that never claims to
  interpret camera frames.
- **`simulated`** (`ACTIVITY_BACKEND=sim`, or any injected `sim_script`):
  scripted timeline; kept for tests and backwards compatibility.
- **future**: a real activity model plugs in at the same seam with the same
  `Detection` shape — no other component changes; state machine, `/ws`, REST
  and the dashboard are agnostic to the perception backend. The object-detection
  overlay (`/api/detections`) remains an independent, honest sidebar until a
  real activity model exists.

## Roadmap (from the SIH problem statement)

Phase 1 (current): dashboard + FastAPI + WebSocket + configurable simulator.
Phase 2+: OpenCV webcam pipeline → object detection (YOLO/ONNX) → pose/hand
detection → rule-based recognition → temporal ML → voice alerts (Piper),
local recording/streaming, offline packaging.
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
                     │   SimulatedPerception   (swappable)        │
                     └────────────────────────────────────────────┘
                              ▲
              (later)  OpenCV → YOLO → Pose → Activity Recognition
```

## Perception vs. decision-making

The core design rule (enforced in both backend and frontend):

- **Perception** asks *"what action is happening?"* and emits a `Detection`
  (`activity`, `confidence`, `ts`).
- **Decision-making** is the *experiment state machine*, which asks *"is this
  action valid at the current step?"* and emits classified `Event`s.

The simulator and the future camera pipeline are interchangeable because both
produce the exact same `Detection` shape. The state machine, WebSocket
protocol and dashboard never know (or care) which one is live.

## Configurable experiment definitions

Experiment sequences are JSON documents in `backend/experiments/`. The active
definition is the first in sorted order — dropping in a new sequence requires
no code changes. Schema:

```json
{
  "id": "bas-box-sequence-01",
  "name": "BAS Box Sequence",
  "description": "…",
  "steps": [
    { "id": "s1", "activity": "PICK_MAIN_BOX", "label": "Pick main experiment box",
      "action": "PICK", "object": "MAIN_BOX" }
  ]
}
```

The frontend bundle ships the same sequence as a fallback
(`frontend/src/domain/experiment.ts`) for offline/local mode.

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

## Replacing the simulator (Phase 4+)

1. Implement a perception module in `ai/` yielding `Detection` objects.
2. In `backend/app/main.py`, swap `SimulatedPerception` for the new source
   (same `.detections()` async iterator contract).
3. No other component changes — state machine, `/ws`, REST and the dashboard
   are agnostic to the perception backend.

## Roadmap (from the SIH problem statement)

Phase 1 (current): dashboard + FastAPI + WebSocket + configurable simulator.
Phase 2+: OpenCV webcam pipeline → object detection (YOLO/ONNX) → pose/hand
detection → rule-based recognition → temporal ML → voice alerts (Piper),
local recording/streaming, offline packaging.
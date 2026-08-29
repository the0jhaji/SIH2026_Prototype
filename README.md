# BAS-AI — SIH 2026 PS 26174

Offline AI-based Human Activity Recognition for on-board experiment assistance on
Bharatiya Antariksh Station (BAS). The system watches a fixed camera feed,
recognizes predefined experiment activities against a **configurable** step
sequence, validates order, guides the operator, detects errors, issues voice
alerts, logs timestamped events, and records video locally.

This is an **SIH prototype**, not flight-qualified software. Reliability over
fancy UI.

## Core rule

The deployed system **must work fully offline**:

- No cloud APIs, no OpenAI/Gemini/Claude, no cloud DBs, no cloud TTS.
- All inference, validation, logging and speech stay on the local machine.

## Design principle

**Perception is separated from decision-making.**

- Perception: *"What action is happening?"* → a `Detection` (`activity`, `confidence`).
- State machine: *"Is this action valid now?"* → a classified `Event`
  (`STEP_MATCHED`, `OUT_OF_SEQUENCE`, `SKIPPED_STEP`, `REPEATED_STEP`,
  `UNKNOWN_ACTIVITY`, `LOW_CONFIDENCE`).

No LLM is ever used as the mission-critical sequence validator.

## Repository layout

```
frontend/   React + Vite + Tailwind dashboard (Phase 1 complete)
backend/    FastAPI + WebSocket + SQLite (Phase 2) — planned
ml/         OpenCV / YOLO / MediaPipe perception pipeline — planned
```

The perception → state-machine flow is already wired end-to-end using a
**simulated** perception source, so the dashboard, reducer, event model and
logs are identical to what the real pipeline will feed in later phases.

## Current status

| Phase | Goal | Status |
|-------|------|--------|
| 1 | React dashboard with simulated activity events | done |
| 2 | FastAPI backend + WebSocket | next |
| 3 | Experiment state machine (server side) | modelled in `domain/reducer.ts` |
| 4–11 | OpenCV, detection, pose, recognition, voice, recording, packaging | planned |

## Running the dashboard (Phase 1)

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173 and press **Start experiment**. A scripted
simulation replays the initial experiment (pick main box → open → pick/place
RED → pick/place YELLOW) and deliberately injects every supported error type:

- out-of-sequence (picks YELLOW when RED was expected)
- skipped step advisory
- repeated step
- unknown activity
- low-confidence detection

## Initial experiment (configurable)

1. Pick main experiment box
2. Open experiment box
3. Pick RED box
4. Place RED box in target area
5. Pick YELLOW box
6. Place YELLOW box in target area

The sequence is plain data in `frontend/src/domain/experiment.ts` — no code
changes needed to reorder or extend the procedure.

## Coding rules observed

- Clean modular code; minimal dependencies (no UI/state libraries).
- No cloud services, no hardcoded secrets.
- Perception (`sources/`) is a swappable interface; the UI never sees it.
- Error handling and logging throughout.
- Offline TTS (Piper) planned for voice alerts — nothing cloud-based.

## Phase 1 module map

```
frontend/src/
  domain/
    types.ts            shared event/detection/step model
    experiment.ts       configurable experiment definitions
    reducer.ts          classification state machine (pure, testable)
  sources/
    types.ts            EventSource interface (perception boundary)
    SimulatedSource.ts  scripted fake perception
    WebSocketSource.ts  Phase-2 real source (ready)
  hooks/
    useExperiment.ts    controller: wires source → reducer → state
  components/
    LiveFeed.tsx        simulated fixed-camera feed (canvas)
    StatusPanel.tsx     detected activity, confidence, expected step, errors
    StepChecklist.tsx   completed / current / next steps
    EventLog.tsx        timestamped log
    Header.tsx          status, recording, start/stop
```

The state machine in `domain/reducer.ts` is pure and unit-tested directly with
Node's native type stripping:

```bash
cd frontend
npm run test:reducer
```
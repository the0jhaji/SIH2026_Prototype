# BAS-AI — SIH 2026 PS 26174

Offline AI-based **Human Activity Recognition** for on-board experiment
assistance on Bharatiya Antariksh Station (BAS). A fixed camera watches the
operator, the system recognises predefined experiment activities against a
**configurable** sequence, validates their order, detects errors, and drives a
live monitoring dashboard — fully offline.

This repository contains the **software prototype foundation**: a React
dashboard, a FastAPI backend, WebSocket streaming and a configurable
experiment simulator. Real AI perception (CV / YOLO / pose) comes in later
phases. **No cloud services, no cloud TTS, no LLM validation.**

## Monorepo layout

```
frontend/   React + Vite + Tailwind dashboard
backend/    FastAPI server (REST + WebSocket + state machine + simulator)
ai/         perception pipeline (planned: OpenCV → YOLO → Pose → HAR)
models/     model weights (git-ignored, not committed)
data/       runtime data: recordings/ and logs/ (git-ignored)
docs/       architecture and design notes
```

## Architecture in one breath

```
Simulator (scripted detections)          — future: OpenCV/YOLO/pose pipeline
   │  Detection {activity, confidence, ts}
   ▼
Experiment state machine (backend)       — the ONLY authority on step validity
   │  classified Events
   ▼
WebSocket (/ws) ──state snapshots──► React dashboard (real-time updates)
REST           ──start/stop/status/logs
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
```

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
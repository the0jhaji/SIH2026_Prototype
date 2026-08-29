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
.\.venv\Scripts\python.exe -m pytest        # run tests
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### Frontend (`frontend/`)

```powershell
npm run dev              # dev server (port 5173, proxies /api & /ws to :8000)
npm run build            # tsc -b && vite build
npm run lint             # oxlint
npm run test:reducer     # state-machine parity test (Node type-stripping)
```

**Always run `npm run lint` and `npm run build` after frontend changes, and
`python -m pytest` after backend changes.**

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
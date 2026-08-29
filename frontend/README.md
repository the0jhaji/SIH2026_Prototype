# BAS-AI frontend

React + Vite + TypeScript + Tailwind dashboard for the BAS-AI experiment
assistant. See the repository `README.md` for architecture and how to run.

## Scripts

```bash
npm install           # first time
npm run dev           # dev server (port 5173, proxies /api + /ws to :8000)
npm run build         # tsc -b && vite build
npm run lint          # oxlint
npm run test:reducer  # state-machine parity test (Node type-stripping)
```

## Key modules

- `src/hooks/useExperiment.ts` — coordinates `backend` (WebSocket) and `local`
  (simulated) modes.
- `src/domain/` — shared types, configurable experiment definition, and the
  client-side reducer used in local mode.
- `src/sources/` — perception-source abstraction: `BackendSource` (FastAPI ws)
  and `SimulatedSource` (browser-side script).
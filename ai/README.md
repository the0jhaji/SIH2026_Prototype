# ai/ — Perception pipeline (planned)

This directory will hold the real perception stack that replaces the
simulator in `backend/app/simulator.py`:

```
Camera (OpenCV capture)
  → Object detection (YOLO / ONNX Runtime)
  → Pose + hand detection (MediaPipe / YOLO pose)
  → Feature extraction
  → Activity recognition (rule-based → temporal ML, e.g. LSTM)
  → Detection(activity, confidence, ts)   ← the backend seam
```

## The contract

Everything downstream only depends on the `Detection` object
(`backend/app/schemas.py`), the same shape the simulator already emits:

```json
{ "activity": "PICK_RED_BOX", "confidence": 0.93, "ts": 1725000000000 }
```

The state machine (`backend/app/state_machine.py`) classifies the activity
against the configurable experiment sequence. **Perception never decides
validity; the state machine does.**

## Implementation phases (later)

1. Rule-based baseline (location + presence of objects governs PICK/PLACE).
2. Temporal ML wrapper (sliding window over detection confidence streams).

Nothing in here is required for the current prototype — see phase notes in
`docs/ARCHITECTURE.md`.
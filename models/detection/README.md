# models/detection/

Weights for the **backend object-detection layer** (`ai/detection/yolo_detector.py`,
wired through `backend/app/detection_service.py`), the Phase 3 counterpart to
`models/yolo/` (which serves `ai/pipeline/`).

Like everything in `models/`, this is **not committed** and **never
auto-downloaded**. Place an exported ONNX model here by hand — e.g. the small
official COCO YOLOv8n for a demo:

```bash
yolo export model=yolov8n.pt format=onnx        # then copy yolov8n.onnx here
```

The default model path (override anytime with `DETECTION_MODEL_PATH`) is:

- `detection/yolov8n.onnx` → `<repo>/models/detection/yolov8n.onnx`, or
- any absolute path, or
- `$BAS_MODELS_DIR/detection/yolov8n.onnx` if that directory is set.

## Class names

Default classes (index-aligned with the BAS-AI 5-class model), bit-identical
to the pipeline's `DEFAULT_CLASSES`:

```
person, experiment_box, red_box, yellow_box, target_area
```

If a `.names` file (one class per line) sits **next to the ONNX file** — e.g.
`yolov8n.names` — it overrides the list. Use that for a custom-trained model.

## ⚠️ Important limitation

A **generic pretrained YOLO model (COCO, etc.) does not recognise these
experiment-specific classes** — COCO has `person` but not `red_box`,
`yellow_box`, `experiment_box`, or `target_area`, and its boxes don't match
anything the state machine consumes. For a real pipeline you must:

1. collect/label BAS-AI footage,
2. train (or fine-tune) a model with the 5 classes above,
3. export to ONNX and drop it here.

Until then, `DETECTION_BACKEND=mock` is the honest demo path: it emits
deterministic `person 0.95 / red_box 0.91 / yellow_box 0.89` detections on the
live camera feed so the dashboard, API, and overlays work end-to-end without
weights.

## Behaviour when missing

With `DETECTION_BACKEND=yolo` and no model present, the app **starts fine**;
`GET /api/detection/status` reports `modelLoaded: false` and an
`error` explaining the missing path. It never crashes and never downloads.
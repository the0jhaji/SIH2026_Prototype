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

Class names are picked up (index-aligned, one per line) from the `.names`
file **next to the ONNX file** — there is no hardcoded class list in code.
The current `yolov8n.names` is extracted **from the model's own metadata**
(the embedded COCO-80 list: `person`, `bicycle`, ..., `toothbrush`), so the
detector reports exactly the classes the loaded model can actually detect,
and only those.

If a `.names` file (one class per line) sits **next to the ONNX file** — e.g.
`yolov8n.names` — it overrides the list. Use that for a custom-trained model
(`dataset/scripts/install_detection_model.py` writes it from
`classes.json`). Keep it index-aligned with the ONNX output, or the ID→name
mapping and the <configured> class filter will silently drop or mislabel
detections.

## ⚠️ Important limitation

A **generic pretrained YOLO model (COCO, etc.) does not recognise the Astra
experiment classes** — COCO has `person` but not `red_box`, `yellow_box`,
`experiment_box`, or `target_area`, so those specific classes simply never
appear. The COCO model does however detect its own 80 everyday classes
(`person`, `bottle`, `cup`, `chair`, `cell phone`, ...), all of which flow to
the hazard/safety layer honest and unclassified unless `hazards.json` maps
them.

Until then, two honest no-weights paths exist:

- `DETECTION_BACKEND=heuristic` — real pixels, no model: `person` from motion,
  `red_box`/`yellow_box` from saturated colour. Works live; imperfect on skin
  tones/shadowing, and it deliberately never claims the `experiment_box` or
  `target_area` classes (only a trained model sees those).
- `DETECTION_BACKEND=mock` — deterministic `person 0.95 / red_box 0.91 /
  yellow_box 0.89` demos so the dashboard, API, and overlays work end-to-end
  without weights.

Either way, the activity feed (`ACTIVITY_BACKEND=live`, the default) will wait
honestly at any step whose `expectedObjects` includes `experiment_box` /
`target_area` until the trained YOLO model is installed below — the experiment
never completes out of thin air.

## Training pipeline (Phase 4C)

The repo already carries the full loop from annotated dataset to a runtime
model. Everything is local — nothing is downloaded or uploaded.

```powershell
# 1. Collect + annotate (dataset/README.md: record_dataset.py -> annotation/app.py),
#    then produce the session-aware split:
.\\.venv\\Scripts\\python.exe dataset\\scripts\\prepare_split.py --root dataset
.\\.venv\\Scripts\\python.exe dataset\\scripts\\validate_dataset.py --root dataset

# 2. Export a validated ultralytics data.yaml from the split:
.\\.venv\\Scripts\\python.exe dataset\\scripts\\export_training.py --root dataset
#    -> dataset/training/data.yaml  (fails with exit 2 on missing labels or
#       cross-split session leakage; never splits a session across sets)

# 3. Train + export (dedicated venv, this file's neighbour keeps the core venv lean):
python -m venv .venv-train
.venv-train\\Scripts\\pip install -r dataset\\requirements-train.txt
.venv-train\\Scripts\\yolo train data=dataset\\training\\data.yaml model=yolov8n.pt epochs=200 imgsz=640
.venv-train\\Scripts\\yolo export model=runs/detect/train/weights/best.pt format=onnx

# 4. Install the export for the runtime (copies ONNX + writes the .names file
#    straight from annotation/classes.json, so class ids always match):
.\\.venv\\Scripts\\python.exe dataset\\scripts\\install_detection_model.py \\
    --onnx runs/detect/train/weights/best.onnx

# 5. Run the backend with the trained model:
$env:DETECTION_ENABLED="true"; $env:DETECTION_BACKEND="yolo"
.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000 --reload --app-dir backend
#    GET /api/detection/status -> modelLoaded=true and your trained classes
```

`install_detection_model.py` and the runtime detector agree on one contract:
a `.names` file (one class per line, index-aligned) sitting next to the ONNX
overrides the default class list. The `.names` file is the training
vocabulary, so you never hand-edit a class list in code.

## Everyday-objects model (Roboflow set)

Separate from the app's experiment-scene dataset, the repo carries a
downloaded **15-class everyday-objects** set (`dataset/roboflow/`) that also
trains the same runtime detector — useful for recognising common objects (Bag,
Bottle, Cup, Watch, ...) alongside person/boxes. See `dataset/README.md`
("Roboflow everyday-objects set") for the full prepare → train → evaluate →
install loop. Its model installs to `roboflow.onnx` + `roboflow.names` (leaving
the app's `yolov8n.onnx`/`.names` untouched) and is selected with
`DETECTION_MODEL_PATH=detection/roboflow.onnx`.

## Fastest way to see detection running (no weights)

```powershell
# from backend/: deterministic mock camera + mock detector
.\run_mock_demo.ps1     # DETECTION_ENABLED=true, DETECTION_BACKEND=mock
# from backend/: live heuristic detector on a real webcam
.\run_camera_demo.ps1   # DETECTION_ENABLED=true, DETECTION_BACKEND=heuristic
```

## Behaviour when missing

With `DETECTION_BACKEND=yolo` and no model present, the app **starts fine**;
`GET /api/detection/status` reports `modelLoaded: false` and an
`error` explaining the missing path. It never crashes and never downloads.
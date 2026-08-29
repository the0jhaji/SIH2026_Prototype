# ai/ — Local computer-vision perception pipeline

Standalone OpenCV perception stack (Phase 3). It runs and tests **without
FastAPI** — the backend wiring is added in a later phase.

```
Camera / NullSource (OpenCV capture)
  → BaseDetector.detect(frame)
      mock            synthetic, deterministic (no model)
      yolo            YOLOv8 ONNX via cv2.dnn (weights in ../models/yolo)
  → ObjectDetection list + annotated frame
  → CLI preview / console output
```

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

.\.venv\Scripts\python.exe -m pytest                    # 39 tests
.\.venv\Scripts\python.exe -m pipeline.cli --detector mock               # live preview (webcam)
.\.venv\Scripts\python.exe -m pipeline.cli --detector mock --source null  # demo, no webcam
.\.venv\Scripts\python.exe -m pipeline.cli --detector mock --headless --print-detections
```

## The detector interface

`pipeline/base.py:BaseDetector` — implement `detect(frame, timestamp_ms=None)
-> list[ObjectDetection]`. Every detector returns the same structure, so the
pipeline, preview, and the future backend seam stay detector-agnostic:

```json
{
  "class_name": "red_box",
  "confidence": 0.93,
  "bounding_box": [412, 188, 96, 74],
  "timestamp": 1725000000000
}
```

| Module          | Purpose                                                     |
| --------------- | ----------------------------------------------------------- |
| `detections.py` | `Box`, `ObjectDetection` + JSON contract                    |
| `base.py`       | `BaseDetector` interface                                    |
| `mock.py`       | `MockDetector` — synthetic person/experiment_box/red_box/yellow_box/target_area; no model needed |
| `yolo.py`       | `YoloDetector` — YOLOv8 ONNX via `cv2.dnn`, letterboxing, class-aware NMS, no auto-download |
| `webcam.py`     | `FrameSource`, `WebcamSource` (camera), `NullSource` (synthetic frames) |
| `annotate.py`   | `draw_detections` — boxes + labels on a *copy* of the frame |
| `pipeline.py`   | `CameraPipeline` — source → detector → annotate → callback loop |
| `cli.py`        | preview window / JSON-lines CLI (independent of the backend) |

## YOLO detector

- Weights: drop an ONNX export into `models/yolo/` (see `models/README.md`).
  Nothing is downloaded automatically — `YoloDetector.load()` raises a clear
  `FileNotFoundError` when weights are missing.
- Default classes: `person, experiment_box, red_box, yellow_box, target_area`.
- Post-processes both `(1, 4+C, N)` and `(1, N, 4+C)` exports; letterbox
  resizing; class-aware NMS.

## Next phase

Map `ObjectDetection` streams into the `Detection(activity, confidence, ts)`
contract consumed by `backend/app/state_machine.py` (Phase 4 onwards), then
swap `backend/app/simulator.py` for the camera pipeline.
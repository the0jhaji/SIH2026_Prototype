# ai/ — Local computer-vision perception pipeline

Standalone OpenCV perception stack (Phase 3). It runs and tests **without
FastAPI** — the backend wiring is added in a later phase. Phase 4 adds the
hand/object interaction module (`pipeline/interaction/`) that produces
temporal hand⇄object observations from the same detections plus hand
landmarks.

```
Camera / NullSource (OpenCV capture)
  → BaseDetector.detect(frame)
      mock            synthetic, deterministic (no model)
      yolo            YOLOv8 ONNX via cv2.dnn (weights in ../models/yolo)
  → ObjectDetection list + annotated frame
  → BaseHandTracker.track(frame)      (mock synthetic / MediaPipe local)
  → InteractionTracker.update()       HAND_NEAR / MOVED / PLACED events
  → CLI preview / console output
```

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

.\.venv\Scripts\python.exe -m pytest                    # 91 tests
.\.venv\Scripts\python.exe -m pipeline.cli --detector mock               # live preview (webcam)
.\.venv\Scripts\python.exe -m pipeline.cli --detector mock --source null  # demo, no webcam
.\.venv\Scripts\python.exe -m pipeline.cli --detector heuristic --source null --print-detections  # model-free demo
.\.venv\Scripts\python.exe -m pipeline.cli --detector mock --headless --print-detections
.\.venv\Scripts\python.exe -m pipeline.cli --interaction --headless --print-detections  # demo interaction chain
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
| `hand.py`       | 21-keypoint hand landmarks: `BaseHandTracker` / `MockHandTracker` / lazy `MediaPipeHandTracker` (weights in `../models/pose`) |
| `annotate.py`   | `draw_detections` — boxes + labels on a *copy* of the frame |
| `pipeline.py`   | `CameraPipeline` — source → detector → annotate → callback loop |
| `cli.py`        | preview window / JSON-lines CLI (independent of the backend) |

## Hand/object interaction (Phase 4)

`pipeline/interaction/` turns per-frame object detections + hand landmarks
into honest low-level observations. It is a **perception** module — it never
classifies an activity and never makes a step-validity decision (that stays
exclusively with `backend/app/state_machine.py`).

| Module        | Purpose                                                      |
| ------------- | ------------------------------------------------------------ |
| `events.py`   | `InteractionEvent` + the six event names below               |
| `geometry.py` | `hand_proximity`, `object_diagonal`, `centre_inside_box` (pure, no state) |
| `tracker.py`  | `InteractionTracker.update(detections, hands, frame_size, timestamp) -> list[InteractionEvent]` — object/hand continuity, temporal moving↔stable state |
| `demo.py`     | `MockScene` + `make_hand` — deterministic demo driving the full chain; re-projects authored 1280×720 coordinates to the frame size |

Event semantics (events carry `name`, `object`, `confidence`, `timestamp`,
`hand_id`, `distance_px`, `displacement_px`, `in_target_area`):

- `HAND_NEAR_RED` / `HAND_NEAR_YELLOW` — a hand is within `near_mult` × object
  diagonal of the box centre. **Observational only**; emitted on enter
  transitions (debounced).
- `RED_MOVED` / `YELLOW_MOVED` — the object's centre displaced more than
  `move_mult` × object diagonal for `min_move_frames` (2) consecutive frames.
  Proximity alone never fires it; jumps across detection gaps don't count.
- `RED_PLACED` / `YELLOW_PLACED` — after a confirmed move episode, the object
  came to rest (`settle_frames` consecutive frames within `settle_mult`) **and**
  its centre is inside the target area (bloated by `target_margin`). An object
  already resting at its target is *not* "placed".

`InteractionConfig` defaults: `near_mult=0.90`, `move_mult=0.30`,
`min_move_frames=2`, `settle_mult=0.10`, `settle_frames=3`, `idle_frames=30`,
`target_margin=0.15`, `max_assoc_distance=0.25` (fraction of frame diagonal,
object continuity), `hand_assoc_distance=0.25` (fraction of frame diagonal,
hand continuity).

`MediaPipeHandTracker` needs `pip install mediapipe-tasks` into a supported
Python and a `hand_landmarker.task` file in `models/pose/`. Import and model
load are lazy — the whole stack (including all tests) runs without MediaPipe;
`MockHandTracker` is the always-available path.

## YOLO detector

- Weights: drop an ONNX export into `models/yolo/` (see `models/README.md`).
  Nothing is downloaded automatically — `YoloDetector.load()` raises a clear
  `FileNotFoundError` when weights are missing.
- Default classes: `person, experiment_box, red_box, yellow_box, target_area`.
- Post-processes both `(1, 4+C, N)` and `(1, N, 4+C)` exports; letterbox
  resizing; class-aware NMS.

## Backend detection layer (`detection/`)

`detection/` is the **Phase 3 glue**: a small, self-contained contract that
the FastAPI backend drives (`backend/app/detection_service.py` runs it on the
camera feed). Where the pipeline detects for the *demo/hand* stack, this layer
detects for the *dashboard* — same spirit, pixel-space boxes:

```json
{
  "class_name": "red_box",
  "confidence": 0.91,
  "x1": 204, "y1": 345,
  "x2": 332, "y2": 431,
  "timestamp": 1725000000000
}
```

| Module | Purpose |
| --- | --- |
| `types.py` | `Detection` (frozen, `x1/y1/x2/y2`, `to_dict`, epoch-ms `timestamp`) + `DetectorStatus` |
| `detector.py` | `BaseDetector` interface + `create_detector(kind, ...)` factory |
| `mock_detector.py` | deterministic mock — `person 0.95 / red_box 0.91 / yellow_box 0.89`, boxes scale with frame size, `scene="empty"` yields none |
| `yolo_detector.py` | ONNX via `cv2.dnn`, reuses the pipeline's `letterbox` / `postprocess_yolov8` / `resolve_weights_path`; optional `.names` file overrides classes |
| `dual_yolo.py` | runs independently configured general + custom ONNX models sequentially, then merges them with cross-model NMS |

`YoloDetector` defaults to `detection/yolov8n.onnx` (i.e. `models/detection/`,
see that README for the generic-pretrained-model limitation). Tests:
`tests/test_detection.py`. `ai/__init__.py` + `conftest.py` let the backend
import this package (`import ai.detection`) while `ai/.venv` pytest keeps
importing `pipeline.*` / `detection.*` directly.

## Next phase

Map `ObjectDetection` + interaction-event streams into the
`Detection(activity, confidence, ts)` contract consumed by
`backend/app/state_machine.py`, then swap `backend/app/simulator.py` for the
camera pipeline.
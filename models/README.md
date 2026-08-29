# models/

Location for trained model weights used by the perception pipeline (`ai/`).

Deliberately **not committed** to the repository (large binaries), and never
auto-downloaded. Place exported files here by hand.

| Directory    | Contents                                              |
| ------------ | ----------------------------------------------------- |
| `yolo/`      | YOLO object-detection weights as **ONNX** exports (`yolov8n.onnx` by default; export a `.pt` with `yolo export model=... format=onnx`) |
| `detection/` | ONNX weights for the backend detection layer (`ai/detection/yolo_detector.py`); default `detection/yolov8n.onnx`, optional sibling `.names` file overrides the class list — see `detection/README.md` |
| `pose/`      | MediaPipe hand-landmark model **`hand_landmarker.task`** (used by `ai/pipeline/hand.py:MediaPipeHandTracker`; needed only for real hand tracking — the mock path needs nothing) |
| `har/`       | temporal activity-recognition weights                  |

## How the pipeline finds weights

Resolution order for every module:

1. absolute path, else
2. `$BAS_MODELS_DIR/<name>`, else
3. `<repo>/models/<path>/<name>`

Dataset labels used by the default detector
(`ai/pipeline/yolo.py:DEFAULT_CLASSES`):

```
person, experiment_box, red_box, yellow_box, target_area
```

See `ai/README.md` for the pipeline and the detection JSON contract.
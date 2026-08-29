# models/

Location for trained model weights used by the perception pipeline (`ai/`).

Deliberately **not committed** to the repository (large binaries), and never
auto-downloaded. Place exported files here by hand.

| Directory    | Contents                                              |
| ------------ | ----------------------------------------------------- |
| `yolo/`      | YOLO object-detection weights as **ONNX** exports (`yolov8n.onnx` by default; export a `.pt` with `yolo export model=... format=onnx`) |
| `pose/`      | MediaPipe hand-landmark model **`hand_landmarker.task`** (used by `ai/pipeline/hand.py:MediaPipeHandTracker`; needed only for real hand tracking — the mock path needs nothing) |
| `har/`       | temporal activity-recognition weights                  |

## How the pipeline finds weights

`ai/pipeline/yolo.py` and `ai/pipeline/hand.py` resolve a model in this
order:

1. absolute path, else
2. `$BAS_MODELS_DIR/<name>`, else
3. `<repo>/models/<path>/<name>`

Dataset labels used by the default detector
(`ai/pipeline/yolo.py:DEFAULT_CLASSES`):

```
person, experiment_box, red_box, yellow_box, target_area
```

See `ai/README.md` for the pipeline and the detection JSON contract.
# ASTRA Model-Configuration Diagnostic

Date: 2026-09-25 · host: Windows, 16 logical CPUs, OpenCV 5.0.0, NumPy 2.5.2.
No training was run. No model was replaced.

---

## A. Which model ASTRA currently uses

`.\start.ps1` (verified by running it, `-Test`):

```
[DETECTION RUNTIME]
  backend         = yolo
  model path      = ...\models\detection\yolov8n.onnx
  model size      = 12.85 MB
  model type      = ONNX (OpenCV DNN, CPU)
  role            = GENERAL / PRIMARY
  class count     = 80
  class names     = person, bicycle, car, motorcycle, airplane, bus, train, truck ... (+72 more)
  input size      = 640
  conf threshold  = 0.25
  iou threshold   = 0.45
  cv threads      = 8
  ai rate         = target 8.0 fps / actual 0.0 fps
  inference       = idle (ms)
  objects         = 0 stable / 0 raw
  trace logging   = False
```

Config resolution, in order: no `.env` file exists anywhere in the repo and
`backend/app/config.py` never calls `load_dotenv`, so **the environment
`start.ps1` sets is the only source**. `start.ps1` sets
`DETECTION_BACKEND=yolo`, `DETECTION_MODEL_PATH=detection/yolov8n.onnx`,
`DETECTION_CONF_THRESHOLD=0.25`, `DETECTION_CV_THREADS=8`.

## B. Model identity (proved from the tensors, not the filenames)

| model | size | output | classes | `.names` | role |
|---|---|---|---|---|---|
| `models/detection/yolov8n.onnx` | 12.85 MB | `(1, 84, 8400)` | **80** | `yolov8n.names`, 80 lines, COCO | **general / primary** |
| `models/detection/experiment_custom.onnx` | 12.27 MB | `(1, 6, 8400)` | **2** | `experiment_custom.names`, 2 lines | specialised only |

`experiment_custom.onnx` is retained, untouched, and is reachable only via
`DETECTION_BACKEND=dual`.

## C. Why only person was detected

**Three independent causes, all confirmed empirically. None of them is the model.**

### C1. `DETECTION_CONF_THRESHOLD` was 0.50 (the primary cause)

Raw sweep, 14 real 1280×720 frames from `dataset/raw`, `yolov8n.onnx` only:

| conf | total detections | class breakdown |
|---|---|---|
| 0.10 | 55 | person 26, laptop 15, chair 5, book 3, bottle 2, dining table 1, suitcase 1, sink 1, banana 1 |
| 0.20 | 38 | person 20, laptop 12, book 3, chair 2, sink 1 |
| **0.25** | **32** | **person 16, laptop 12, chair 2, book 1, sink 1** |
| 0.30 | 27 | person 15, laptop 12 |
| 0.40 | 21 | person 11, laptop 10 |
| **0.50** | **15** | **person 8, laptop 7** |

Per-frame stage counts showed the mechanism directly:

```
frame_000001  RAW(cand>=0.10)=29  -> after conf 0.50 = 3   (26 dropped)
frame_000002  RAW(cand>=0.10)=26  -> after conf 0.50 = 0   (26 dropped)
frame_000003  RAW(cand>=0.10)=27  -> after conf 0.50 = 0   (27 dropped)
histogram >=0.10: {'person': 19, 'laptop': 7, 'suitcase': 1}
```

`bottle 0.17`, `book 0.28`, `suitcase 0.13`, `dining table 0.12`, `chair 0.16`
were all **being detected** and then thrown away. 0.50 is YOLOv8's *NMS* score
floor, not a sensible reporting threshold. **Fixed: default is now 0.25.**

### C2. `DETECTION_CV_THREADS=0` silently pinned OpenCV to one core

`config.py` documented `0` as "leaves OpenCV's auto-detect untouched", but
`YoloDetector.load()` did `cv2.setNumThreads(1)` in the `else` branch. The code
contradicted its own documented contract. Measured (14 frames, conf 0.25):

| cv_threads | preprocess | inference | postprocess | total | FPS |
|---|---|---|---|---|---|
| 1 (old `0` path) | 12.31 ms | **666.18 ms** | 132.41 ms | 810.90 ms | 1.23 |
| 2 | 10.71 | 417.83 | 130.68 | 559.23 | 1.79 |
| 4 | 10.45 | 320.72 | 137.72 | 468.89 | 2.13 |
| **8** | 10.55 | **293.27** | 129.48 | **433.30** | **2.31** |
| 16 | 12.34 | 307.03 | 129.33 | 448.71 | 2.23 |

**Fixed: default is 8, and `0` now genuinely leaves auto-detection alone.**

### C3. The status banner reported a different model than the one in use

`YoloDetector` resolves its vocabulary from the `.names` file inside `load()`,
but `load()` was lazy (first `detect()`), while `DetectionService._bootstrap`
read `status()` immediately. The first real `start.ps1` run printed:

```
class count     = 5
class names     = person, experiment_box, red_box, yellow_box, target_area
model size      = unknown
role            = SPECIALISED (narrow vocabulary - CANNOT detect person/bottle/cup!)
```

i.e. the 5-entry `DEFAULT_CLASSES` placeholder, not the 80 COCO names.
Detection itself was correct, but the *identity* was a lie — exactly the kind of
thing that makes "prove which model is actually running" impossible. Caught by
the new guard, then **fixed: `load()` is now eager in `_bootstrap`**, so the
banner above is the truth (80 classes, 12.85 MB).

## D. Where objects disappear (no person-only filter exists)

Audited every `person` reference in `backend/app/**` and `ai/**` and every
class-name filter. **There is no person-only allowlist anywhere** — no
`allowed_classes=["person"]`, no `classes=[0]`, no `class_id==0` gate.
`postprocess_yolov8` filters only on `scores >= conf_threshold` and
`class_ids < num_classes`. The `person` matches in `attendance.py` are all
"find the nearest person to compare against an object", which is correct.

The pipeline is therefore transparent:

```
RAW YOLO        26-29 candidates/frame  (person, laptop, book, bottle, chair,
                                         suitcase, dining table, sink, ...)
  ↓ confidence filter (was 0.50)        → 0-3     <-- EVERYTHING LOST HERE
  ↓ class filter (80 COCO, all valid)   → no change
  ↓ unknown-object merge (motion only)  → +unknown_object proposals, no loss
  ↓ TemporalTracker (debounce 2, EMA)   → promotes after 2 consecutive frames
  ↓ safety world model / hazard engine  → reads detections, filters nothing
  ↓ API /api/detections                 → all classes, unfiltered
  ↓ CameraView "Detections" list        → renders every entry
```

## E. Existing trained models in the repo

| path | size | task | classes | class names | verdict |
|---|---|---|---|---|---|
| `yolov8n.pt` (repo root) | 6.55 MB | detect | 80 | COCO-80 | stock upstream base, nothing ASTRA-specific |
| `runs/detect/experiment_custom/weights/best.pt` | 24.46 MB | detect | 2 | `red_box`, `yellow_box` | **is** the source of `experiment_custom.onnx` (50 epochs, 272 train imgs) |
| `runs/detect/experiment_custom/weights/last.pt` | 24.46 MB | detect | 2 | same | final-epoch variant of the above |
| `dataset/runs/probe_small/weights/best.pt` | 6.25 MB | detect | **15** | `Bag, Book, Bottle, Cell Phone, Cup, Fork, Keys, Laptop, Paper, Pen, Spects, Spoon, Stairs, Wallet, Watch` | **the only ASTRA-vocabulary candidate** — see below |
| `runs/detect/experiment_custom/weights/best.onnx` | 12.27 MB | — | 2 | same | duplicate of the installed custom ONNX |

**`dataset/runs/probe_small/weights/best.pt` is the interesting find.** Its 15
classes are exactly the vocabulary ASTRA cares about — Bottle, Cup, Book, Laptop,
Cell Phone, Pen, Keys, Wallet, Watch. It was trained on
`dataset/roboflow/split` (train 16052 / val 1540 / test 171, a 15-class personal-object
set).

**It must not be promoted as-is, and it is not currently installed.** Its
`args.yaml` records `epochs: 1` — a one-epoch smoke-test probe, not a real
fine-tune. It has no recorded validation metrics, and its sibling `best.onnx`
was never exported. It is reported here as a lead for the *next* stage, exactly
as requested, and no automatic swap was performed.

## F. Final measured baseline (single general model only)

60 real 1280×720 frames, `yolov8n.onnx`, conf 0.25, iou 0.45, `cv_threads=8`,
trace logging **off**, idle host:

| stage | per frame | FPS |
|---|---|---|
| YOLO detect (letterbox + blob + forward + NMS) | **51.1 ms** | **19.6** |
| generic motion proposer | 8.0 ms | |
| **combined AI budget** | **59.1 ms** | **16.9** |

Classes actually observed: `person 67, laptop 15, book 6, chair 3, cell phone 3,
sink 1`.

**This corrects the earlier report.** `docs/PERFORMANCE_AND_UNATTENDED_REPORT.md`
concluded 8–15 AI FPS was unreachable on this host. That conclusion was wrong: it
was derived from measurements taken while `setNumThreads(1)` was in force and
while a stale second backend was competing for the CPU. With the thread bug
fixed and an idle machine, the pipeline runs at **~17–20 AI FPS**, inside the
requested band.

## G. Fixes applied

| # | File | Change |
|---|---|---|
| 1 | `backend/app/config.py` | `DETECTION_CONF_THRESHOLD` 0.50 → **0.25**; added `DETECTION_IOU_THRESHOLD=0.45`; `DETECTION_CV_THREADS` 0 → **8** |
| 2 | `ai/detection/yolo_detector.py` | `0` no longer forces `setNumThreads(1)`; added `_warn_if_narrow()`; added `_check_channel_match()` |
| 3 | `ai/detection/types.py` | `DetectorStatus` gained `input_size`, `conf_threshold`, `iou_threshold`, `model_size_mb`, `general_purpose` |
| 4 | `ai/detection/detector.py` | `iou_threshold` threaded through `create_detector` for `yolo` and `dual` |
| 5 | `ai/detection/dual_yolo.py` | `detector_type` now reports `"dual"` (was `"yolo"`, indistinguishable from the single model); new status fields |
| 6 | `backend/app/detection_service.py` | **eager `load()`** before status; full runtime model log block; `modelSizeMb`/`classCount`/`generalPurpose`/`inputSize`/`iouThreshold` in the API |
| 7 | `backend/app/main.py` | passes `iou_threshold` |
| 8 | `start.ps1` | explicit model roles, `DETECTION_MODEL_PATH`, `DETECTION_CONF_THRESHOLD=0.25`, `DETECTION_CV_THREADS=8`; prints the full `[DETECTION RUNTIME]` block and warns if the loaded model is not general-purpose |
| 9 | `frontend/src/domain/detection.ts` | new `DetectionStatus` fields |
| 10 | `frontend/src/views/CameraView.tsx` | Model panel now shows classes/size/imgsz/conf/iou/**role**, with a prominent warning when a specialised model is loaded |
| 11 | `backend/tests/test_model_config.py` | **new**, 7 tests: both guards, the vocab-mismatch `ValueError`, conf 0.25 vs 0.50, iou propagation |

## H. Verification

| suite | result |
|---|---|
| `backend/.venv -m pytest backend/tests` | exit 0 (incl. 7 new model-config tests) |
| `ai/.venv -m pytest` | 104 passed |
| `backend/.venv -m pytest dataset/tests` | 77 passed |
| `frontend npm run lint` | 0 warnings, 0 errors |
| `frontend npm run build` | `tsc -b` + vite clean |
| `frontend npm run test:reducer` | PASS |
| `.\start.ps1 -Test` | `[DETECTION RUNTIME]` reports the true model |

## I. Known limits, stated honestly

1. **`probe_small/best.pt` is untrained in practice** (1 epoch). It is a lead,
   not a fix. Promoting it without validation would likely *reduce* recall.
2. `yolov8n.onnx` is a **generic COCO** model. It does not know
   `red_box`/`yellow_box`, `floating_tool`, `loose_cable` or any real ASTRA
   equipment class. Those remain un-detectable without the custom model or a
   real fine-tune.
3. The 15-class roboflow vocabulary uses its own labels (`Bottle`, `Cup`,
   `Bag`, `Spects`, …), which are **not** the same as COCO's. Merging them
   requires an explicit mapping, not a merge of raw class ids.
4. `dual` is still ~2× the inference cost. `probe_small` (3.01 M params, 15
   classes) is a candidate to *replace* the general slot with, which would make
   the ASTRA vocabulary available without paying for two forwards — but only
   after it is actually trained and validated.
5. No live-camera verification was possible: the webcam could not be opened
   while another process held it (`-1072875772`). All raw-detection numbers
   above are from real recorded 1280×720 frames, not a live scene.

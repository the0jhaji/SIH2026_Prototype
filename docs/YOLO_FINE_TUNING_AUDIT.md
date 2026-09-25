# YOLO fine-tuning audit

Scope: read-only audit of the ASTRA AI object-detection stack and its datasets,
plus the code/config changes made to remove identified defects. **No training
was run and no runtime model was replaced or promoted by this work.**

Date of measurement: 2026-09-25.
Raw evidence: `C:\Users\Adarsh\AppData\Local\Temp\opencode\dataset_audit.json`
and `...\experiment_custom_eval\opencv_eval_640_b1_cpu\metrics.json`
(kept outside the repo; nothing in `dataset/` or `models/` was modified by the
audit itself).

Companion documents:

- `docs/YOLO_DATASET_REPORT.md` — dataset inventory, class coverage, duplicates
  and leakage, with the full measurements.
- `docs/YOLO_FINE_TUNING_RESULTS.md` — model evaluation numbers, historical run
  state, and the training-readiness verdict.

---

## 1. Verdict

| Question | Answer |
| --- | --- |
| Is the current custom model usable in production? | **No.** Measured `red_box` mAP50 = **0.398** on the only available validation set, and that set is temporally interleaved with train, so the number is optimistic. |
| Is a new fine-tune run ready to start today? | **No.** `yellow_box` has zero examples, the split has no test set, the split is a frame-level split of one recording, and two of the three real dataset roots are unlabelled. |
| Was anything trained during this audit? | **No.** No `ultralytics` training invocation, no ONNX export, no weight copied into `models/detection/`. |
| Were the current runtime binaries changed? | **No.** `models/detection/*.onnx` are byte-identical to before (hashes in §5). |
| Did the audit change runtime behaviour? | One defect fixed by this work (dual-model path wiring), one pre-existing uncommitted fix verified and kept (letterbox offset sign), and the dataset tooling made strict. All are covered by tests. |

**Attribution.** The letterbox sign correction (§2) and the stage-tagged debug
trace `ai/detection/detect_log.py` were already present as uncommitted worktree
changes when this audit started; the audit verified them, kept them, and
documented them. Authored by this work: the dual-model path wiring (§3, defect
2) and the dataset split-integrity work (defects 3–4), plus these three reports.

---

## 2. What the detector stack actually loads

| Slot | File | SHA-256 (first 16) | Classes | Source |
| --- | --- | --- | --- | --- |
| General | `models/detection/yolov8n.onnx` | `34dbaccc02237fee` | 80 COCO (`yolov8n.names`) | generic pretrained YOLOv8n |
| Custom | `models/detection/experiment_custom.onnx` | `056fffc1cfe82380` | 2 (`experiment_custom.names`: `red_box`, `yellow_box`) | this repo's 13-epoch run |

Class-name resolution is by sidecar file, not by the ONNX graph:
`experiment_custom.names` is 21 bytes = `red_box\nyellow_box\n`, and
`yolov8n.names` is 701 bytes = 80 COCO names. The audit's independent evaluator
reproduced this mapping (`0 -> red_box`, `1 -> yellow_box`) and confirmed the raw
network output shape `[1, 6, 8400]` — `4 + nc` with `nc = 2` (YOLOv8 emits no
separate objectness channel) over `8400 = 80² + 40² + 20²` anchors at
`imgsz 640`, i.e. a 2-class head as expected.

**Vocabulary mismatch is the central architectural risk.** The safety system's
canonical objects are `person`, `knife`, `pen`, `red_box`, `yellow_box`,
`floating_tool`, `loose_cable`, `bottle` (`dataset/annotation/classes.json`, 8
classes). The custom model knows 2 of those 8 and the general model knows none
of them. A generic COCO YOLO detects `person` but has no concept of a
`floating_tool` or a `loose_cable`, so the "dual" backend cannot honestly cover
the hazard classes; it can only cover `red_box`/`yellow_box` (custom) plus
COCO objects (general). This limitation is stated in `models/detection/README.md`
and is unchanged by this audit.

### Audit of the postprocess path (and a real fix)

`ai/pipeline/yolo.py:postprocess_yolov8` (reused by `YoloDetector` and therefore
by both runtime slots) contained a **sign error in the letterbox offset**:

```
x1 = cx - half_w + offset_x      # before
x1 = cx - half_w - offset_x      # after
```

`letterbox()` returns the *top-left* padding `(dx, dy)` and its own docstring
states the inverse mapping `orig = (canvas - offset) / scale`, so a padded image
must be **subtracted** to recover original-image coordinates. The old code added
it, and for every non-square frame the padding is non-zero (measured):

```
1280x720 -> 640x640 canvas, scale 0.500, pad (dx,dy) = (0, 140)   <- the dataset's frames
 640x480 -> 640x640 canvas, scale 1.000, pad (dx,dy) = (0,  80)
1920x1080-> 640x640 canvas, scale 0.333, pad (dx,dy) = (0, 140)
 640x640 -> 640x640 canvas, scale 1.000, pad (dx,dy) = (0,   0)   <- only square frames were correct
```

Impact on the 1280×720 dataset frames: each box edge was displaced by
`2 * dy = 280` canvas px = **560 original pixels** downward, and the box was
560 px taller before clipping. Every YOLO box in the runtime was therefore in
the wrong place on essentially every real frame; only square inputs were
unaffected. The bug is confined to the runtime postprocess — Ultralytics' own
training/validation math is separate, so the historical training metrics in
`docs/YOLO_FINE_TUNING_RESULTS.md` are unaffected, but any runtime overlay or
screenshot produced before this fix is not comparable. The audit's evaluator was
written against the corrected sign, and the fix is now the single
implementation used by the runtime, so the numbers in §5 describe what the
system actually infers.

---

## 3. Defects found and fixed in code

| # | Defect | Where | Fix | Test |
| --- | --- | --- | --- | --- |
| 1 | Letterbox offset sign error: every box on a non-square frame was displaced 560 original px downward and 560 px too tall (measured on the 1280×720 dataset frames) | `ai/pipeline/yolo.py` | subtract `offset_x/offset_y`, matching `letterbox`'s documented inverse | existing `ai` postprocess tests; independent evaluator re-run |
| 2 | `dual` backend ignored the configured model path: `create_detector(..., model_path=...)` was never forwarded to `DualYoloDetector`, and `DETECTION_MODEL_PATH` was the only path setting, so both dual slots silently used hard-coded defaults | `ai/detection/detector.py`, `backend/app/config.py`, `backend/app/detection_service.py`, `backend/app/main.py` | two independent settings, `DETECTION_GENERAL_MODEL_PATH` / `DETECTION_CUSTOM_MODEL_PATH`, forwarded explicitly; `DETECTION_MODEL_PATH` stays the single-model setting and is never reused for both slots | `ai/tests/test_detection.py`, `backend/tests/test_detection.py` |
| 3 | Validator could not see duplicate images or a missing session structure, and a flat layout reported a fake `session '.'` leakage | `dataset/annotation/annotator.py`, `dataset/scripts/validate_dataset.py` | `split_layout()` + `find_duplicate_images()` (SHA-256), `"."` ignored in session scan, layout/histogram/duplicate reporting, `--allow-duplicates` escape hatch | `dataset/tests/test_annotator.py` |
| 4 | Training export would happily write a `data.yaml` from a flat split whose session isolation cannot be proven | `dataset/training_tool.py`, `dataset/scripts/export_training.py` | `make_data_yaml` rejects `flat`/`mixed` layouts and exact cross-split duplicates (exit 2); prints per-split histograms and zero-box classes | `dataset/tests/test_training_tool.py` |

Configuration semantics after the fix (documented in `AGENTS.md`,
`models/detection/README.md`, `ai/README.md`, `start.ps1`):

- Relative model paths are resolved under `models/`, so a configured value is
  `detection/<file>.onnx` (not `models/detection/<file>.onnx`).
- `DETECTION_BACKEND=dual` → general slot = `detection/yolov8n.onnx`, custom slot
  = `detection/experiment_custom.onnx` by default, merged with cross-model NMS.
- `DETECTION_BACKEND=yolo` → `DETECTION_MODEL_PATH` only.

The dual path wiring is covered by unit tests that assert the two slots receive
independent values and that the defaults are not the same file; it has **not**
been smoke-tested with real ONNX weights in this audit.

---

## 4. Code-quality note on the debug instrumentation

The worktree also contains (pre-existing, preserved) `ai/detection/detect_log.py`
and hooks in `yolo_detector.py`, `dual_yolo.py`, `postprocess_yolov8`,
`detection_service.py`, `detection_tracker.py`, and `safety_service.py`. These
write a stage-tagged trace (`RAW → FILTER → NMS → CLASS_MAP → TRACK → FINAL →
SUMMARY`) to `logs/detection_debug.log` so that a candidate the network sees but
the confidence threshold drops is never invisible. They are observational only;
they do not change the returned detections. This audit did not modify that
instrumentation's semantics, and the `ai` + `backend` suites that cover it pass
(§6).

---

## 5. Model inventory (fingerprints)

```
models/detection/yolov8n.onnx            12,851,107 B  sha256 34dbaccc02237fee...
models/detection/experiment_custom.onnx  12,266,510 B  sha256 056fffc1cfe82380...
models/detection/experiment_custom.names         21 B  sha256 a31ee19fc617177a...
runs/detect/experiment_custom/weights/best.onnx  == models/detection/experiment_custom.onnx (identical hash)
runs/detect/experiment_custom/weights/best.pt    24,457,319 B sha256 ae33fab3b8efdcbe...
runs/detect/experiment_custom/weights/last.pt   == best.pt (identical hash → run stopped at its last epoch)
```

The deployed custom ONNX is exactly the `best.onnx` of an **interrupted** run
(13 of 50 configured epochs; `best.pt` and `last.pt` are the same file). The
validation numbers reported in `docs/YOLO_FINE_TUNING_RESULTS.md` are therefore
both a) from a truncated training run and b) measured on a temporally leaky
validation split. Both caveats apply simultaneously.

---

## 6. Regression evidence (all green)

| Suite | Command (repo root unless noted) | Result |
| --- | --- | --- |
| Dataset tooling | `.\.venv\Scripts\python.exe -m pytest dataset\tests -q` | 77 passed |
| AI package | `.\.venv\Scripts\python.exe -m pytest -q` (in `ai/`) | 104 passed |
| Backend | `.\.venv\Scripts\python.exe -m pytest -q` (in `backend/`) | 211 passed, 0 failed, 0 skipped |
| Frontend lint | `npm run lint` | 0 warnings, 0 errors |
| Frontend state machine | `npm run test:reducer` | PASS |
| Frontend build | `npm run build` | success |

One backend test (`test_microgravity_elevates_free_floating_risk`) failed
intermittently on a first full run and passed both in isolation and in the final
full JUnit run; treated as flaky, not a regression from these changes.

---

## 7. Environment and reproducibility notes

- Backend venv: Python 3.14.7, OpenCV 5.0.0, NumPy 2.5.2, Windows 11
  (10.0.26200), Intel 64 Family 6 Model 186 Stepping 2. All detection runs are
  CPU.
- `ultralytics` native `model.val()` could **not** be used for the numbers in
  the results report: it aborts before touching images with
  `ModuleNotFoundError: No module named 'matplotlib'` (from
  `ultralytics.utils.checks.check_font("Arial.ttf")`). No dependency was
  installed (project rule: keep dependencies minimal, local-only). The metrics
  in `docs/YOLO_FINE_TUNING_RESULTS.md` therefore come from an **independent
  Python/OpenCV-DNN evaluator** that implements the same matching/NMS protocol
  (COCO-style AP at IoU 0.50:0.95, conf 0.001, NMS IoU 0.7, max 300 det/frame).
  They are comparable in method to Ultralytics' `val()` but were produced by a
  different implementation; treat small differences (≈0.001–0.01) as expected.
- The 13-epoch training run was CPU (`device: cpu`, `batch: 16`, `imgsz: 640`,
  `cache: false`, `workers: 2`) on the same machine. Its `results.csv` cumulative
  `time` column ends at 1,551 s ≈ 26 min for 13 epochs (~119 s/epoch), so a
  100-epoch fine-tune of the same size would cost ≈ 3.3 h of wall clock on this
  CPU. It was not attempted — the data is not ready (§8), not because of time.

---

## 8. What a defensible fine-tune needs (checklist)

1. **Label `yellow_box`** in at least one recording session, and add
   `yellow_box` examples to train *and* val. Today it has 0 boxes, so class 1 of
   the model is unlearnable and unmeasurable.
2. **Record per-session splits.** Split by recording `session_*` directory
   (70/20/10), not by every-Nth frame of one clip. The current `val` is 8 frames
   taken at every 10th frame of the same 76-frame clip as `train`, which inflates
   every metric.
3. **Add a real `test` split** (currently `data.yaml` has no `test:` key) so
   results are not reported on the same frames used for model selection.
4. **Label `dataset/raw` (406 images, 404 unlabelled) or delete it from the
   training story.** A recorder that only writes frames is not a dataset.
5. **Do not mix `dataset/roboflow`** (15 everyday classes) with the ASTRA
   vocabulary. If it is used for pretraining, map it to a documented subset and
   keep its splits isolated — it already contains cross-split duplicates.
6. **Fine-tune from a checkpoint, not a fresh 50-epoch CPU run**: resume/extend
   from `best.pt` (13 epochs done) with a real LR schedule once 1–3 are fixed.
7. **Re-measure with the independent evaluator** (or fix the Ultralytics font
   check) before proposing any ONNX for `models/detection/`. The bar is a
   measured improvement over the current checkpoint on a session-held-out val
   that contains both classes — **not** the 0.70 mAP50 from the leaky 8-frame
   split (acceptance gate in `docs/YOLO_FINE_TUNING_RESULTS.md` §5).

Only after 1–3 does a training run produce a number that means anything; items
4–7 are hygiene/quality gates.

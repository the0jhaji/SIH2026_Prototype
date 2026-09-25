# YOLO fine-tuning and evaluation results

What the current custom model actually achieves, what the previous training run
did, and whether a new fine-tune should be started. **No new training was run
for this report and no model was promoted to `models/detection/`.**

Measurement date: 2026-09-25. All numbers are CPU.
Companion documents: `docs/YOLO_FINE_TUNING_AUDIT.md` (code/architecture audit),
`docs/YOLO_DATASET_REPORT.md` (data audit).

---

## 1. Headline: the deployed custom model is not production-usable

`models/detection/experiment_custom.onnx` (sha256 `056fffc1…`) evaluated on the
**entire available validation set** — 8 images, 20 `red_box` instances, 0
`yellow_box` instances — with an independent Python/OpenCV-DNN evaluator
(COCO AP@0.50:0.95, conf 0.001, NMS IoU 0.7, max 300 det/frame, `imgsz 640`,
batch 1):

| Metric | `red_box` (class 0) | `yellow_box` (class 1) |
| --- | --- | --- |
| Instances (val) | 20 | **0** |
| Precision | 0.483 | undefined (no GT) |
| Recall | 0.350 | undefined |
| mAP50 | 0.398 | undefined |
| mAP50-95 | 0.246 | undefined |
| F1 (at best conf) | 0.406 | undefined |
| Best mean-F1 confidence | 0.159 | — |

Overall (the only evaluable class): precision 0.483, recall 0.350,
mAP50 0.398, mAP50-95 0.246, F1 0.406.

Read this as **“the model half-finds red boxes on an easy, leaky 8-frame
validation set, and knows nothing measurable about yellow boxes.”** It is not a
statement about real-world accuracy: 8 validation images from the *same clip* as
training cannot support a confidence claim, and precision/recall at the operating
point the runtime actually uses (`DETECTION_CONF_THRESHOLD` default **0.5**) are
lower still, because the best mean-F1 confidence is only 0.159.

Per-image detail (at IoU 0.50, with predictions capped at 300/frame):

| val image | GT boxes | true positives @ IoU .5 | max conf |
| --- | --- | --- | --- |
| `frame_00000` | 3 | 3 | 0.806 |
| `frame_00010` | 3 | 3 | 0.302 |
| `frame_00020` | 6 | 4 | 0.798 |
| `frame_00030` | 2 | 2 | 0.812 |
| `frame_00040` | 2 | 2 | 0.732 |
| `frame_00050` | 1 | 1 | 0.753 |
| `frame_00060` | 2 | 1 | 0.295 |
| `frame_00070` | 1 | 0 | 0.057 |

Even before any fine-tuning: the model floods the frame with candidates (every
image hit the 300-detection cap at conf 0.001; ~200 `red_box` and ~100
`yellow_box` candidates per image) and its *useful* confidences top out around
0.3–0.8 on 8 frames. The full candidate stream per frame is visible in
`logs/detection_debug.log` at runtime (the `RAW`/`FILTER` trace); the runtime
`TemporalTracker` (2-frame debounce, EMA 0.35) is what currently keeps that
flood from reaching the dashboard.

> These numbers are measured with the **corrected** letterbox inverse. Before
> that fix, the runtime postprocess placed every box 560 original pixels too low
> on a 1280×720 frame (see `docs/YOLO_FINE_TUNING_AUDIT.md` §2), so any runtime
> overlay captured from the old code understates the model — and no historical
> runtime observation should be compared against this table.

---

## 2. Latency (CPU, batch 1, 1280×720 input → 640 letterbox)

| stage | ms / image |
| --- | --- |
| preprocess (letterbox) | 7.5 |
| inference (`cv2.dnn` forward) | 31.9 |
| postprocess (NMS + decode) | 17.2 |
| **complete pipeline** (excl. matching) | **57.9** |
| warm-up inference | 35.8 |
| first timed inference | 38.0 |

The dual backend runs the two ONNX models **sequentially** and then cross-model
NMS, so a dual frame costs roughly 2× the above (~120–140 ms/frame end-to-end
plus merge) on this CPU. That is acceptable for a 10–30 fps dashboard feed but
is a real cost; it was not re-benchmarked in this audit after the path-wiring fix
(the two slots now load the *configured* files, unit-tested but not re-timed).

---

## 3. State of the previous training run (`runs/detect/experiment_custom`)

The only training run in the repo **stopped early**: 13 epochs recorded out of
`epochs: 50` (`patience 20`, so it did not early-stop on patience — it was cut
off externally). `best.pt` and `last.pt` are byte-identical, and `best.onnx` is
byte-identical to the deployed
`models/detection/experiment_custom.onnx` — i.e. **the shipped model is the
best checkpoint of an interrupted 13-epoch run.** Its 13 epochs took 1,551 s
(~26 min, ~119 s/epoch) on CPU, so the full 50 would have been ~1.7 h.

Its last-epoch self-reported metrics (Ultralytics, on the same leaky 8-frame
val):

| metric | value |
| --- | --- |
| precision(B) | 0.740 |
| recall(B) | 0.600 |
| mAP50(B) | 0.703 |
| mAP50-95(B) | 0.288 |

These look better than §1 (mAP50 0.70 vs 0.40) for two reasons, both of which
mean the higher number is the less trustworthy one:

1. **Different evaluator / thresholding.** Ultralytics evaluates at its default
   conf and IoU conventions; the independent evaluator in §1 sweeps conf down to
   0.001 for a proper AP curve. The gap is a warning that these two numbers are
   not interchangeable — the deployed model's real precision/recall at the
   runtime's 0.5 threshold is closer to the §1 column.
2. **Leaky validation.** The 8 val frames are the every-10th-frame subset of the
   same 76-frame clip the 272 train frames come from (see the dataset report).
   A 13-epoch checkpoint on one static clip scores well on its own neighbours;
   this is textbook optimistic validation, not generalisation.

The run also used `yolov8n.pt` as the base with `optimizer: auto`, `lr0: 0.01`,
`batch: 16`, `cos_lr: false`, `device: cpu` — a reasonable smoke-test recipe, but
not the fine-tuning schedule below.

---

## 4. Native Ultralytics validation is currently blocked

`model.val()` on this ONNX aborts before it ever loads an image:

```
ModuleNotFoundError: No module named 'matplotlib'
  in ultralytics.utils.checks.check_font("Arial.ttf")
```

The project's install policy is “minimal dependencies, all local”, and
`matplotlib` is not installed, so this was **not** worked around by installing
packages. The §1 numbers come from the independent evaluator instead. To get
native `val()` numbers back later, either install the training extra
(`dataset/requirements-train.txt`, which is where Ultralytics + matplotlib
belong, in a separate venv) or accept the independent evaluator as the
project's source of truth for ONNX metrics.

---

## 5. Fine-tuning readiness: **not ready** (blockers, in order)

A defensible fine-tune for the ASTRA box experiment needs, at minimum:

1. **`yellow_box` labelled** in at least one session, present in train *and* val.
   Today: 0 boxes project-wide, so class 1 of the 2-class model is unlearnable
   and unmeasurable.
2. **A session-held-out split.** `experiment_train` is a single clip split by
   frame index; the strict exporter now correctly refuses it (exit 2, “flat
   layout”). Annotating a few more independent `raw`/`activity` sessions gives
   the splitter real session directories to hold out.
3. **A real `test` split** in `data.yaml` (absent today) so the reported number
   is not the model-selection set.
4. **No mixing of vocabularies.** Roboflow's 15 classes stay out (and it has its
   own cross-split duplicate + provenance leakage to clean first — dataset
   report §5).

Only after 1–3 should a run be started, and it should **resume/extend from
`best.pt`** rather than restart from scratch. The intended recipe (recorded for
when the data is ready):

```
yolo detect train model=<base>.pt data=<validated data.yaml>
  imgsz=640 epochs=100 batch=8 patience=20
  optimizer=AdamW lr0=0.001 weight_decay=0.0005 cos_lr=True
  workers=4 cache=False deterministic=True
```

Budget: the previous run averaged ~119 s/epoch on this CPU, so ~3.3 h for 100
epochs at the current dataset size — and proportionally more once the labelled
set is actually grown.

Acceptance gate before any ONNX is copied into `models/detection/`: re-run the
independent evaluator on a **session-held-out** val that contains **both**
classes, and require a **measured improvement over the current checkpoint on
that same val** plus absolute floors (mAP50 ≥ 0.5, recall ≥ 0.5 at a stated
confidence), reproduced across a fresh eval. The 0.70 mAP50 in §3 is *not* the
bar — it was measured on frames the model trained on. A candidate model must be
re-validated on held-out data, not assumed from a training log.

---

## 6. Summary table

| Item | Value |
| --- | --- |
| New training runs in this work | **0** |
| Models promoted / replaced | **0** (shipped `experiment_custom.onnx` untouched) |
| Deployed model epochs | 13 of 50 (interrupted) |
| Deployed model, independent-evaluator mAP50 (`red_box`) | **0.398** on an 8-frame val shared with train |
| Deployed model, `yellow_box` | **0 GT — untrainable as-is** |
| Historical Ultralytics mAP50 (same frames, own conventions) | 0.703 |
| Latency, single model CPU | 57.9 ms/frame |
| Latency, dual (sequential estimate) | ~120–140 ms/frame |
| Fine-tune ready? | **No** — needs `yellow_box` labels, session split, test split |

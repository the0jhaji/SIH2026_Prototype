# YOLO dataset report

Read-only inventory, class-coverage, duplicate and leakage audit of every
image root under `dataset/`. **Nothing in `dataset/` was modified by this
audit**; the tooling changes described in §7 are code/test/doc changes only.

Measurement date: 2026-09-25.
Machine-readable evidence: `C:\Users\Adarsh\AppData\Local\Temp\opencode\dataset_audit.json`
(schema `astra-dataset-audit/1`, 11.7 MB, includes every per-pair distance).

Method (as recorded in the JSON `method` block):

- **Exact duplicates** — SHA-256 over raw file bytes for every image; plus
  SHA-256 over RGB-decoded, EXIF-transposed pixels for `experiment_train`,
  `raw` and `activity` (Roboflow images are re-encoded, so only the byte hash
  is meaningful there).
- **Near duplicates** — 64-bit dHash (EXIF-transposed RGB→L, LANCZOS 9×8, one
  bit per adjacent horizontal comparison, MSB first); distance = integer
  Hamming distance over all Cartesian pairs; quantiles nearest-rank.
- **Label consistency** — for every exact image group, paired label bytes,
  SHA-256, row counts, class histograms and per-coordinate deltas.
- **Roboflow provenance** — the filename stem *before* `.rf.<hex>` is treated as
  the underlying source-photo identity (`.rf.<hex>` is a Roboflow augmentation
  tag, not a new image).

---

## 1. Inventory at a glance

| Root | Images | Sessions | YOLO label files | Boxes | Class vocabulary | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `dataset/experiment_train` | 280 (272 train / 8 val) | flat, 1 source sequence | 280 | 516 | 2 (`red_box`, `yellow_box`) — from `data.yaml` | **usable only for `red_box`; val is frame-level from the same clip** |
| `dataset/raw` | 406 | 5 `session_*` dirs | 0 under `raw/`; 2 blank mirrors in `dataset/annotations` | 0 | 8 (`classes.json`) | **not a training set — 404/406 unannotated** |
| `dataset/activity` | 439 | 7 `session_*` dirs (one per activity) | 0 | 0 | activity *names* only (7, not object classes) | **not an object-detection set** |
| `dataset/roboflow/split` | 17,763 (16,052 / 1,540 / 171) | flat, Roboflow export | 17,763 | 18,133 | 15 everyday classes | **wrong vocabulary; has cross-split duplicates** |

Total images on disk: **18,888**. Total usable ASTRA object boxes: **516**, all
`red_box`, all from a single 76-frame recording.

**Class-id namespaces collide.** Three different vocabularies assign meaning to
the *same* integers, and nothing in the label format distinguishes them:

| id | `experiment_train/data.yaml` | `annotation/classes.json` (canonical) | `experiment/experiment.json` objects | Roboflow `data.yaml` |
| --- | --- | --- | --- | --- |
| 0 | `red_box` | `person` | `person` | `Bag` |
| 1 | `yellow_box` | `knife` | `experiment_box` | `Book` |
| 2 | — | `pen` | `red_box` | `Bottle` |
| 3 | — | `red_box` | `yellow_box` | `Cell Phone` |

So a label validated against the wrong file is not an error — it is a silent
relabeling. Every command that touches labels must be given the vocabulary that
belongs to that dataset root (§7 shows this biting in practice).

---

## 2. `dataset/experiment_train` — the only set the current model was trained on

```
images 280 = 272 train + 8 val,  1280x720 JPEG
boxes  516 = 496 train + 20 val,  100% class 0 = red_box
class 1 (yellow_box): 0 boxes anywhere
boxes/image: 1->118, 2->91, 3->70, 6->1
data.yaml: train+val only, no test split
```

**Provenance.** 68 `frame_*` originals + 204 `aug_*` images = 272 train. The
three augmentation families each have 68 images derived 1:1 from those same 68
frames (family 0 = horizontal flip with `cx' = 1-cx`; families 1/2 = additive
brightening+noise / ≈0.7 multiplicative darkening). All 68 augmented labels were
verified to match the geometric transform (0 discrepancies). The 8 val images are
`frame_00000, 00010, … 00070` — the every-10th-frame subset of the **same
apparent 76-frame clip** as the 68 train originals (train originals are the
non-multiples-of-ten frames). So:

- There is exactly **one** recording sequence here, and train/val are two
  interleaved windows of it. Session-level splitting is impossible by
  construction.
- `aug_*` families derive **only** from the 68 train frames — no augmentation of a
  val frame leaked in, which is the one thing this split does right.

**Exact duplicates: none.** Both byte and decoded-pixel SHA-256 give 280 unique
hashes, 0 duplicate groups within or across splits. This is the only root in the
repo that passes the new duplicate check cleanly.

**Near-duplicate leakage across the train/val boundary: present.** dHash
zero-distance groups inside this root: 57 groups / 218 images, of which **5 groups
(43 images, 38 pairs) span train→val**; 38 train images have a *val* image at
distance 0. Consecutive frames of a near-static clip are perceptually identical,
so this is the expected signature of a frame-level split, and it means the val
metrics are optimistic.

**Class coverage: one class, zero examples for the other.** `yellow_box` (class
1) has 0 boxes in train, val and total. The model can never learn it and no
metric can be computed for it.

---

## 3. `dataset/raw` — recorded but essentially unlabelled

5 recording sessions (4 with frames, 1 empty), 406 frames, 1280x720, one
manifest/metadata per session (present, no mismatches):

| session | images | capture label |
| --- | --- | --- |
| `session_20260829_233703_6weu` | 77 | `box_experiment` |
| `session_20260829_235407_o3s3` | 98 | `box_experiment` |
| `session_20260830_000619_gvmb` | 131 | `pick_red_box` |
| `session_20260830_000735_ess9` | 0 | `pick_red_box` (empty) |
| `session_20260830_000747_0vtt` | 100 | `pick_red_box` |

- **404 of 406 images have no annotation mirror** under `dataset/annotations`;
  the 2 mirrors that do exist are **blank** (0 boxes). Total object boxes: 0.
- No YOLO label files live under `raw/` itself; the capture-label column
  (`box_experiment`, `pick_red_box`, …) is a *session name*, not a YOLO class id.
- This is a recorder working as designed (raw capture only, per
  `AGENTS.md` Phase 4A), but it means `raw` contributes **zero** training signal
  until someone runs the annotation tool on it.

---

## 4. `dataset/activity` — activity takes, not object labels

7 sessions, one per activity, 439 frames, 1280x720, 0 label files, 0 object
boxes:

| activity | images |
| --- | --- |
| `APPROACH` | 92 |
| `OPEN_BOX` | 45 |
| `PICK_RED` | 83 |
| `PICK_YELLOW` | 68 |
| `PLACE_RED` | 54 |
| `PLACE_YELLOW` | 97 (26 + 71) |
| `COMPLETE` | **0** |

The "classes" here are the experiment's 7 activity names, not YOLO object
classes. There is nothing to train an object detector on, and one activity
(`COMPLETE`) was never recorded. The session-per-activity layout is genuinely
useful for a future *activity* model and for a session-held-out object split
once objects are annotated inside these takes — it is the best available source
of independent recordings (7 sessions vs 1).

---

## 5. `dataset/roboflow` — correct mechanics, wrong vocabulary, real leakage

`data.yaml` manifest: seed 42, test fraction 0.1, 15 classes.

| split | images | boxes | blank label files |
| --- | --- | --- | --- |
| train | 16,052 | 16,052 | 4,279 |
| val | 1,540 | 1,002 | 538 |
| test | 171 | 110 | 61 |
| total | 17,763 | 18,133 | 4,878 |

Class box histogram (train / val / test):

```
Bag=4980/229/24   Book=8/0/0        Bottle=123/142/23   Cell Phone=2727/6/0
Cup=2293/273/38   Fork=9/1/4        Keys=688/38/1       Laptop=8/11/2
Paper=3/0/0       Pen=1347/172/17   Spects=1767/2/0     Spoon=1281/18/0
Stairs=1100/140/12 Wallet=92/114/14  Watch=83/302/41
```

Findings:

- **Vocabulary is disjoint from ASTRA's 8 object classes.** `Bottle` is the only
  name in common and means a different thing in context. Training on this set
  teaches the wrong 15 classes for the safety system.
- **8 exact byte-duplicate groups cross a split boundary** (16 images): 6 are
  `train`↔`val` and 2 are `train`↔`test`. 19 duplicate groups in total
  (38 images, 19 extra copies): the remaining 11 are within a single split
  (10 in `train`, 1 in `val`).
- **All 19 duplicate pairs have *different* label files** (same class histogram
  and row count, but `83/84` compared normalized coordinates differ, max absolute
  coordinate delta `0.065625`). Byte-identical images with different boxes is a
  labelling inconsistency, not just a duplication artefact.
- **Source-provenance leakage:** by filename stem before `.rf.<hex>`, there are
  9,664 underlying source photos; **103 of them appear in both Roboflow `train`
  and Roboflow `valid`** (`base_provenance_split_combination_counts`:
  train-only 8,084, valid-only 1,477, both 103). Since the prepared split copies
  prepared-train from source-train and prepared-val/test from source-valid
  (all 17,763 files are exact byte copies of their source), those 103 source
  photos contribute images to **both** the prepared train and the prepared
  val/test splits. Roboflow's own re-encode/augmentation hides this from any
  byte-level check.
- The prepared split is otherwise a faithful copy: 16,052/16,052 train and
  1,540/1,540 val + 171/171 test match their source bytes, `seed 42`,
  `test 0.1`, and no filename overlap between source train/valid.

Conclusion: keep Roboflow as an optional *pretraining* source at most, isolated
in its own split, and never merge it into the ASTRA training set.

---

## 6. Cross-root overlap

- **Exact pixels: clean.** Decoded-pixel SHA-256 across
  `experiment_train` + `raw` + `activity` (1,125 images): 0 duplicate groups, 0
  cross-split groups. The three roots are genuinely different images.
- **Perceptual: overlapping.** dHash zero-distance groups across all three roots:
  164 groups / 519 images, of which **9 groups (54 images) span set boundaries**.
  Nearest-neighbour distance from experiment frames to `raw` is 10 (median 24)
  and to `activity` is 9 (median 23); experiment val→raw min 16 (median 25),
  val→activity min 14 (median 22). These are different takes of the same physical
  setup, not duplicates, but any combined train/val must still be split by
  session, not by frame.

---

## 7. Tooling changes made in response to these findings

Code (all behind tests; see `docs/YOLO_FINE_TUNING_AUDIT.md` §6 for the green
suite):

- `dataset/annotation/annotator.py`
  - `split_layout(root)` → `session` / `flat` / `mixed` / `empty`.
  - `find_duplicate_images(root)` → byte-exact (SHA-256) duplicate groups as
    root-relative paths.
  - `find_session_leakage` now ignores the `"."` pseudo-session, so a flat split
    reports "unverifiable" instead of a fake `session '.'` leak.
  - `validate_dataset(..., allow_duplicates=False)` now treats cross-split byte
    duplicates as **errors** (downgradable with `allow_duplicates=True`),
    records per-split class histograms and zero-box classes, and warns on
    flat/mixed layouts.
- `dataset/scripts/validate_dataset.py`
  - `--classes` accepts `classes.json` **or** a Roboflow `data.yaml`;
  - `--allow-duplicates`; prints layout, per-split box histograms, session
    leakage, and duplicate groups.
- `dataset/training_tool.py` / `dataset/scripts/export_training.py`
  - `make_data_yaml` refuses to write a `data.yaml` from a `flat`/`mixed` layout
    (no provable session isolation) or with cross-split exact duplicates —
    exit code 2; prints layout, histograms, and per-split zero-box warnings.

Docs updated: `AGENTS.md`, `dataset/README.md`, `models/detection/README.md`.

Behaviour on the real data after the change:

```
# ASTRA experiment split (flat, honest warning, no fake leakage, no dups)
validate_dataset.py --root dataset\experiment_train --classes dataset\annotation\classes.json
  -> Split layout: flat
     train  images= 272  labels= 272  missing=0
     val    images=   8  labels=   8  missing=0
     Session leakage: 0      Duplicate images: cross-split=0  within-split=0
     Warnings (1): flat split layout: no recording-session directories,
                   session isolation cannot be verified (280 images)
     RESULT: OK - dataset is clean

# Roboflow (duplicates allowed, but reported)
validate_dataset.py --root dataset\roboflow\split --classes dataset\roboflow\split\data.yaml --allow-duplicates
  -> Split layout: flat
     cross-split groups=8   within-split groups=11
     Warnings (20)  ->  RESULT: OK

# Training export refuses the flat experiment split
export_training.py --root dataset\experiment_train
  -> exit 2: "Export failed: split layout is 'flat': training export requires
     recording-session directories under each split so session isolation is provable"
```

Note the first run's histogram: with the 8-class `classes.json` it reports
`person=496 / person=20` for the experiment split. That is **not** a labelling
error — it is the class-id incompatibility of §1 (`experiment_train`'s
`data.yaml` says class 0 = `red_box`, `classes.json` says class 0 = `person`).
The experiment root must always be validated with its own `data.yaml`; passing
the canonical 8-class vocabulary against it silently relabels every box.

---

## 8. Prioritized remediation

1. **Label `yellow_box`** and add it to train+val (blocks any `yellow_box`
   claim; the model head is 2-class and class 1 is empty).
2. **Rebuild the split per recording session** — annotate ≥3 more
   `pick_*`/`*_box` sessions from `raw`/`activity` so `make_split` can run on a
   session tree; today `experiment_train` cannot pass the strict export.
3. **Add a real `test` split** to `data.yaml` (currently absent).
4. **Annotate `raw`** (404 unlabelled frames) or keep it strictly out of the
   training narrative; the empty `session_20260830_000735_ess9` can be dropped.
5. **Record the missing `COMPLETE` activity** (0 frames) and keep the 7
   activity sessions as the future activity-model / object-split source.
6. **Quarantine Roboflow**: own vocabulary, own splits; if used for pretraining,
   de-duplicate the 8 cross-split groups, reconcile the 19 mismatched duplicate
   labels, and drop the 103 provenance-spanning photos.
7. **Re-run the audit** after 1–3 and only then start a fine-tune; re-measure on
   a session-held-out val containing both classes.

All numbers above are reproducible from
`C:\Users\Adarsh\AppData\Local\Temp\opencode\dataset_audit.json` (the audit
script is `dataset_audit.py` in the same temp folder). No image, label, or
`data.yaml` in the repository was edited by the audit.

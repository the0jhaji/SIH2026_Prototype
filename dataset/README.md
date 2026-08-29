# dataset/ — Local BAS experiment dataset

Collects a **custom, local-only** dataset for training the BAS-AI object
detector (the phase after this one). Everything stays on this machine — there
is **no upload, no cloud, no network dependency** in the recorder.

## Structure

| Path | Purpose |
| --- | --- |
| `raw/`             | untouched recording **sessions** (one directory per take) |
| `frames/`          | curated/organized frames ready for training (filled in a later phase) |
| `annotations/`     | label files (`YOLO`-style) for the curated frames (later phase) |
| `scripts/record_dataset.py` | recorder CLI |
| `dataset_tool.py`  | shared logic: session creation, metadata, manifest (pure, testable) |
| `tests/`           | session + configuration tests (no camera/device needed) |

## Requirements

The recorder reuses the **exact camera configuration** of the production
backend (`backend/camera/capture.py`, defaults: webcam index `0`,
`1280×720 @ 30fps`). Use the backend venv (it already has OpenCV):

```powershell
.\.venv\Scripts\python.exe dataset\scripts\record_dataset.py          # backend venv, from repo root
```

## Recording

```
usage: record_dataset.py [--camera-index N] [--width W] [--height H] [--fps F]
                         [--interval SECONDS] [--label NAME] [--output DIR] [--mock]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--camera-index` | `0` | webcam device index |
| `--width` / `--height` | `1280×720` | capture resolution |
| `--fps` | `30` | capture frame rate |
| `--interval` | `1.0` | seconds between **saved** frames while recording (0.5 is handy for quick action takes) |
| `--label` | `misc` | activity/object class; slugified into the session path (`PICK_RED_BOX` → `raw/pick_red_box/…`) |
| `--output` | `dataset/` | dataset root; sessions land under `raw/<label>/` |
| `--mock` | off | synthetic mock camera — no webcam needed (for smoke-testing) |

A live preview window shows the camera, a real-time FPS readout, the frames
saved so far, and the save interval. Keys:

- **SPACE** — start / stop recording
- **Q** or **ESC** — quit (releases the camera, writes final metadata)

### Example

```powershell
# One label per activity/pose; record several takes per label.
.\.venv\Scripts\python.exe dataset\scripts\record_dataset.py --label PICK_RED_BOX --interval 0.5
.\.venv\Scripts\python.exe dataset\scripts\record_dataset.py --label PLACE_RED_BOX --interval 0.5
```

Each session is a fresh directory:

```
dataset/raw/pick_red_box/session_20260829_143051_a3f9/
    frame_000001.jpg   # one JPEG per interval tick
    frame_000002.jpg
    …
    manifest.csv       # nickname per saved frame: index, ISO time, epoch-ms
    metadata.json      # camera config, interval, label, frames saved, session id
```

`metadata.json` is written when the session starts and refreshed on quit
(with `ended_at` and the final `frames_saved`), so every take is
self-describing.

## Guidance

- Keep the background/lab lighting and table layout similar to the real
  deployment camera so the trained model generalizes.
- Record both the action and a short idle/"empty" take per scene (an
  `empty` label helps the detector learn negatives).
- The recorder never alters `dataset/raw/` sessions; curation and labeling
  happen in later phases into `frames/` + `annotations/`.

## Tests

```powershell
backend\.venv\Scripts\python.exe -m pytest dataset\tests -q
```

Covers configuration validation (mirroring the backend camera defaults),
unique session creation, label slugging, `metadata.json` round-trips, the
`manifest.csv` format, and directory layout. No camera or display needed.
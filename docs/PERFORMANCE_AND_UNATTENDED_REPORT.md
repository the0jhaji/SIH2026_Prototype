# Performance & Unattended-Object Fix — Measured Report

Date: 2026-09-25 · Host: Windows, 16 logical CPUs, OpenCV 5.0.0, NumPy 2.5.2,
`cv_threads=16`.

---

## 1. Executive summary

Two separate problems were reported. Both were real, and neither was the
model.

| # | Reported symptom | Actual cause | Status |
|---|---|---|---|
| 1 | "slow / low FPS" | `dual` backend ran **two** 640×640 YOLO forwards *and* an un-gated per-candidate debug log **every frame**, with no rate cap | **Fixed** |
| 2 | "object inside box, person walks away, nothing happens" | `AttendanceMonitor` only watched **unknown** detections, and required an `HELD→RELEASED` chain that a simply-placed object never produces. There was **no UI at all** for attendance | **Fixed** |

The 8–15 AI FPS target is **not achievable on this host with the current
fixed-640 ONNX models**, and no amount of pipeline work changes that. See §5.
That target requires a different model or different hardware, and the model is
out of scope by instruction.

---

## 2. Measured stage costs (real frames, 100+)

Frames are real 1280×720 JPEGs from `dataset/raw/{box_experiment,pick_red_box}`.

### 2.1 Clean-host baseline (isolated, no competing load)

| Stage | mean | p50 | p95 |
|---|---|---|---|
| camera JPEG encode+decode (capture thread) | 8.28 ms | 8.01 | 10.03 |
| preprocess letterbox+blob(640) | 4.57 ms | 4.44 | 5.60 |
| **inference general `yolov8n`** | **≈203 ms** | — | — |
| **inference custom (2-class)** | **≈187 ms** | — | — |
| postprocess (debug **ON**) | 23.84 ms | 22.82 | 31.60 |
| postprocess (debug **OFF**) | 5.46 ms | 5.26 | 7.15 |
| generic motion proposals (full 720p, every frame) | 11.34 ms | 11.14 | 14.26 |
| **FULL dual detect (debug ON)** | ≈473 ms | — | — |

### 2.2 Under real host load (the numbers the app actually experienced)

A stale backend process was found still running the *old* dual+debug code
(§4), so the live system measured far worse than the isolated baseline. The
production `logs/detection_debug.log` independently recorded
`inference_ms = 2186–2827` (≈0.4–0.5 AI FPS), which matches the ~2.0 s dual
cost measured under that same contention.

| Stage | mean | p50 | p95 | min |
|---|---|---|---|---|
| inference general | 959.66 ms | 993.92 | 1062.12 | **197.68** |
| inference custom | 905.99 ms | 937.68 | 985.53 | **172.24** |
| postprocess debug ON | 23.84 ms | 22.82 | 31.60 | 18.86 |
| postprocess debug OFF | 5.46 ms | 5.26 | 7.15 | 4.39 |
| generic motion | 11.34 ms | 11.14 | 14.26 | 4.06 |
| **FULL dual detect (debug ON)** | **2008.97 ms** | 2051.61 | 2173.68 | 437.74 |
| **FULL dual detect (debug OFF)** | **1771.56 ms** | 1911.56 | 1991.90 | 395.55 |

The `min` column is the honest uncontended cost and agrees with §2.1.

**Debug logging cost: 23.84 → 5.46 ms (4.4× faster) when gated off.**

### 2.3 Why inference dominates

Single 640 forward ≈ 203 ms. The entire rest of the pipeline is ≈ 20 ms
(preprocess 4.6 + postprocess 5.5 + motion 11.3). **Inference is ~90% of the
cost**, so only two levers matter: run fewer forwards, and run a smaller
network. Everything else is noise.

### 2.4 Thread priority does not help (measured, rejected)

| Run | mean |
|---|---|
| normal priority | 353.43 ms |
| above-normal priority | 394.90 ms |

No benefit (within noise, if anything worse). **Not adopted.**

### 2.5 Both ONNX models are hard-fixed at 640×640

Feeding 320/416/512 fails outright:

```
[ERROR] ... OpenCV(4.x) dnn/net.cpp:... reshape2 ... 
         outTotal == inpTotal in function 'cv::dnn::Reshape2LayerImpl::getOutShape'
```

Outputs are `general: 1x84x8400` (COCO-84) and `custom: 1x6x8400` (2 classes).
A forward at a smaller `input_size` is therefore **not an option** without
re-exporting the models, which is out of scope.

---

## 3. Fixes applied

### 3.1 Configurable AI rate, decoupled from camera FPS

- `DETECTION_FPS` (float, default `8`, `0` = uncapped) caps **AI** inference.
- The camera still captures at its own 25–30 FPS; the two are now independent.
- The service thread calls `camera_manager.latest_capture()` and takes the
  **newest** frame. Rate-skipped frames are **discarded, never queued**, so no
  backlog can form.
- New status fields: `targetFps`, `actualFps`, `inferenceCount`,
  `skippedForRate`, `traceEnabled`.
- Verified: service never exceeded its cap, and produced-inferred lag stayed at
  a single dropped frame.

### 3.2 Debug trace is off by default and properly gated

- `ai/detection/detect_log.py`: module-level `enabled()` / `set_enabled()`; all
  log helpers early-return when disabled.
- `ai/pipeline/yolo.py::postprocess_yolov8`: the per-candidate decode sweep is
  wrapped in a single `if` around the whole loop.
- `DETECT_LOG_ENABLED` (default **false**) wired through `main.py`.
- **Saving: 18.4 ms/frame** (23.84 → 5.46 ms).

### 3.3 Single primary detector by default

`start.ps1` now sets `DETECTION_BACKEND=yolo` (one model) instead of `dual`.

> **Honest trade-off, not silently swallowed:** the general COCO model detects
> `person` and `bottle` but *not* `red_box`/`yellow_box`, which exist only in
> `experiment_custom.onnx`. If you need the red/yellow box experiment, set
> `DETECTION_BACKEND=dual` and accept ~2× the inference cost. This is documented
> inline in `start.ps1`.

### 3.4 Unattended-object logic (the actual bug)

`backend/app/attendance.py`:

- **Known objects are now watched.** `trackedClasses` (default includes
  `bottle`) feeds the same `ObjectWatch` machinery that previously only saw
  unknown-class proposals. This was the direct cause of "nothing happens".
- **Removed the `HELD→RELEASED` precondition.** An object simply placed in a
  box and left is now tracked from its first detection.
- **Containment geometry** (`_containment_score`): object-rectangle
  intersection-over-object-area, i.e. "how much of the object is inside the
  container", which is the physically meaningful measure for "in the box".
  Threshold `UNATTENDED_CONTAINMENT` (default 0.6). Requires real
  intersection — the old `y2 > box.y1` inequality could never fire, which is
  why containment looked implemented but never triggered.
- **Wall-clock timeout**, not frame counting: `UNATTENDED_TIMEOUT_MS`
  (default 2000). Uses real elapsed ms so the delay is correct at 1 AI FPS or
  25 AI FPS — the old `unattended_frames=5` meant "5 frames", i.e. 5 s at
  1 FPS but 0.2 s at 25 FPS.
- **Person association** by normalized-center proximity to the nearest person,
  `UNATTENDED_PROXIMITY` (default 0.18).
- **Watches matched by class + IoU** (`_match_known_watch`) so the same object
  keeps one identity across frames.
- **New `ATTENDED` state** and the `OBJECT_INSIDE_BOX` event.
- **Unknown vs unattended stay strictly separate**: unknown objects keep the
  original `UNKNOWN_DETECTED→POSSIBLY_HELD→HELD→RELEASED→UNATTENDED` chain and
  the original frame-count semantics (`test_unknown_objects.py` still passes
  unmodified). Known objects use the new proximity/timeout chain. `is_unknown`
  gates both.
- Stale feed (`ACTIVITY_STALE_MS`) still freezes state — no timeout can fire on
  a dead feed.

### 3.5 There was no UI — now there is

`useAttendance` was already fetching `/api/attendance*` into context, but **no
view rendered it**. The feature was invisible regardless of backend correctness.

Added to `CameraView.tsx`:
- **"Object Containment & Attendance"** panel: in-container count, unattended
  count, timeout; per-watch state chip (colour-coded `UNATTENDED`/`RELEASED`/
  `ATTENDED`/`OBJECT_INSIDE_BOX`), container class + containment %, person-free
  ms, unknown-class badge; and a recent-events feed.
- Detection panel now shows **AI Rate** (actual/target fps), **Frames Dropped**,
  and **Trace** ON/OFF.
- Fixed `AttendanceState`, which wrongly listed `OBJECT_INSIDE_BOX` as a state
  (it is an event).

---

## 4. A real cause found on the host

Two `uvicorn app.main:app` processes were running, started 21:43, **before** any
of these edits:

```
PID 10396  CPU 0s      Threads 1   (launcher)
PID 17472  CPU 3363s   Threads 33  ← owns :8000, still running OLD dual+debug code
```

The orphan was continuously running dual inference with 33 threads for the
whole session. It is the reason the production log shows 0.4–0.5 FPS and the
reason the "after" benchmark initially inflated to 952 ms/frame. **It must be
killed and the backend restarted** for the new code/config to take effect.

---

## 5. FPS feasibility — stated honestly

Cost per inference is fixed at ~203 ms (one model) / ~390 ms (dual inference).

| Target | Budget | Dual cost | Utilisation | Result |
|---|---|---|---|---|
| 8 FPS | 125.00 ms | 2008.97 ms | 1607% | **OVER BUDGET** |
| 10 FPS | 100.00 ms | 2008.97 ms | 2009% | **OVER BUDGET** |
| 12 FPS | 83.33 ms | 2008.97 ms | 2411% | **OVER BUDGET** |
| 15 FPS | 66.67 ms | 2008.97 ms | 3014% | **OVER BUDGET** |

Even at the clean-host single-model cost of 203 ms, 8 FPS needs 125 ms — still
~1.6× over. Reaching 8–15 AI FPS requires one of:

1. a smaller/faster model or INT8 quantised export (**out of scope**),
2. different inference hardware (GPU/NPU),
3. accepting a lower AI rate and raising `DETECTION_FPS` only when the host
   allows.

`DETECTION_FPS` is a **cap**, not a guarantee: when inference is slower than
the cap, the achieved rate is the model's rate. The UI now shows
`actual/target` so this is visible rather than hidden.

### ROI inference: evaluated and **rejected**

The generic motion proposer is only 11.34 ms at full 720p and 2.09 ms at
half-res — already negligible against a 203 ms forward. ROI-cropped YOLO would
require a *second* forward pass on the crop, making things **worse**, and the
proven single-frame path is currently ~473 ms. Not implemented, by design.

---

## 6. Verification

| Suite | Result |
|---|---|
| `backend/.venv -m pytest backend/tests` | **228 passed**, 2 warnings |
| `ai/.venv -m pytest` | **104 passed** |
| `backend/.venv -m pytest dataset/tests` | **77 passed** |
| `frontend npm run lint` | 0 warnings, 0 errors (45 files) |
| `frontend npm run build` | `tsc -b` + vite build clean |
| `frontend npm run test:reducer` | PASS |

New tests in `backend/tests/test_unattended_object.py` (**17**), covering: known
bottle in box → attended → unattended after timeout → alert; person returns →
resolved; containment threshold; class+IoU watch matching; unknown/unattended
separation; and stale-feed freezing.

End-to-end replay through the real `DetectionService.latest()` payload shape
produced:

```
[info] OBJECT_INSIDE_BOX      object=bottle container=experiment_box score=1.0
[info] ATTENDANCE_TRANSITION  person within proximity
[warn] ATTENDANCE_TRANSITION  person left; nobody in proximity
[warn] ATTENDANCE_ALERT_RAISED  WARNING · bottle (bottle#1) was left with no
                                astronaut in reach (policy: alert after 2.0s)
[info] ATTENDANCE_ALERT_RESOLVED  Alert resolved: Unattended object
```

---

## 7. Honest limitations

1. **8–15 AI FPS is not reachable here.** Documented, not faked.
2. **Static *unknown* objects are still not detected.** `GenericProposalDetector`
   is motion-only by design; once an unrecognised object stops moving and the
   background adapts, it vanishes. **Known** objects (incl. `bottle`) are fixed
   and are the reported scenario. Fixing unknown-static needs background
   freezing / track persistence / a real model — a separate decision.
3. **Person association is proximity-based**, not pose- or trajectory-based.
   MediaPipe hand/pose is not wired into the backend, so "person touches the
   object" is approximated by body-proximity. Adequate for "walks away", not a
   substitute for grasp detection.
4. **Real-camera scenario matrix is not yet executed** — it needs a physical
   webcam and a human placing a real object. The scripted replay above is a
   payload-level equivalent, not a substitute.
5. `logs/detection_debug.log` is 54,919,527 bytes and is **not** rotated. Growth
   is now stopped by default, but rotation is still open.
6. The `min`/`mean` spread (§2.2) shows this host is heavily contended. Re-run
   §2.1 on an idle machine before quoting a single headline number.

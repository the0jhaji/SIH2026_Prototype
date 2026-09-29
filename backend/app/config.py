import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Where configurable experiment definitions (.json) live.
EXPERIMENTS_DIR = BASE_DIR / "experiments"

# Shared storage root (logs, recordings) for the monorepo.
DATA_DIR = BASE_DIR.parent / "data"

# Classification is rejected below this confidence.
CONFIDENCE_THRESHOLD = 0.5

# Maximum number of events retained in the in-memory log ring buffer.
LOG_LIMIT = 400

# Simulator pacing. Tests override this with a fast script.
SIM_STEP_MS = 200


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, low: int, high: int) -> int:
    """Clamped integer env var. A typo must not take the app down at import."""
    try:
        return max(low, min(int(os.environ.get(name, "").strip() or default), high))
    except (TypeError, ValueError):
        return default


# Camera (Phase 2). Override with CAMERA_INDEX / CAMERA_WIDTH / CAMERA_HEIGHT /
# CAMERA_FPS / CAMERA_MOCK. Mock mode keeps the dashboard fully functional on
# machines without a webcam. CAMERA_BACKEND selects the capture API to try
# (auto probms msmf -> dshow -> any and adopts the first that serves valid
# pixels); CAMERA_REJECT_BLACK keeps a dead/black sensor from masquerading as
# a live feed; CAMERA_WARMUP_FRAMES is the per-backend probe budget.
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "720"))
CAMERA_FPS = int(os.environ.get("CAMERA_FPS", "30"))
CAMERA_MOCK = _env_bool("CAMERA_MOCK")
CAMERA_JPEG_QUALITY = int(os.environ.get("CAMERA_JPEG_QUALITY", "70"))
CAMERA_BACKEND = os.environ.get("CAMERA_BACKEND", "auto").strip().lower()
CAMERA_REJECT_BLACK = not _env_bool("CAMERA_ALLOW_BLACK")
CAMERA_WARMUP_FRAMES = int(os.environ.get("CAMERA_WARMUP_FRAMES", "5"))

# Object detection (Phase 3). OFF by default so the app boots without any
# model weights. Enable with DETECTION_ENABLED=true and pick the backend:
#   mock      -> deterministic demo detections (person/red_box/yellow_box)
#   yolo      -> your trained YOLO ONNX in models/detection/ (Phase 4C)
#   dual      -> general + custom ONNX, merged with cross-model NMS
#   heuristic -> model-free HSV color + motion detection, no weights needed
DETECTION_ENABLED = _env_bool("DETECTION_ENABLED")
DETECTION_BACKEND = os.environ.get("DETECTION_BACKEND", "mock").strip().lower()
DETECTION_MODEL_PATH = os.environ.get("DETECTION_MODEL_PATH", "detection/yolov8n.onnx")
DETECTION_GENERAL_MODEL_PATH = (
    os.environ.get("DETECTION_GENERAL_MODEL_PATH", "").strip() or "detection/yolov8n.onnx"
)
DETECTION_CUSTOM_MODEL_PATH = (
    os.environ.get("DETECTION_CUSTOM_MODEL_PATH", "").strip() or "detection/experiment_custom.onnx"
)
# Minimum score for a candidate to be reported. 0.25 is the YOLOv8 default and
# is what the raw sweep on dataset/raw showed is required to see anything beyond
# the most obvious object: at 0.50 the same frames yielded 15 detections
# (person+laptop only), at 0.25 they yielded 32 across 5 classes, at 0.10
# 55 across 9. Raising this silently hides real objects — it does not make the
# detector "stricter", it just deletes the low-confidence majority.
DETECTION_CONF_THRESHOLD = float(os.environ.get("DETECTION_CONF_THRESHOLD", "0.25"))
DETECTION_IOU_THRESHOLD = float(os.environ.get("DETECTION_IOU_THRESHOLD", "0.45"))
DETECTION_POLL_MS = int(os.environ.get("DETECTION_POLL_MS", "10"))
# OpenCV thread pool for the DNN forward. Measured on this 16-logical-CPU host
# (14 real 1280x720 frames, yolov8n 640): inference was 666ms with 1 thread vs
# 293ms with 8 threads — a 2.3x difference. The previous behaviour forced
# setNumThreads(1) whenever this was 0, which silently pinned the detector to a
# single core. 0 now means "leave OpenCV's auto-detect alone", as documented.
DETECTION_CV_THREADS = int(os.environ.get("DETECTION_CV_THREADS", "8"))
# Temporal smoothing of the live detector output (raw -> stable feed):
#   - DETECTION_DEBOUNCE_FRAMES: consecutive frames a class/box must persist before
#     it is emitted as a stable detection (2-3 recommended; 1 disables debounce).
#   - DETECTION_EMA_ALPHA: EMA weight for confidence + box smoothing (0..1).
DETECTION_DEBOUNCE_FRAMES = int(os.environ.get("DETECTION_DEBOUNCE_FRAMES", "2"))
DETECTION_EMA_ALPHA = float(os.environ.get("DETECTION_EMA_ALPHA", "0.35"))

# Detection rate decoupled from the camera rate. The camera keeps serving 25-30 FPS
# for the live view; AI perception runs at its own budget and simply consumes the
# NEWEST frame each time it wakes. Measured on this host, one yolov8n 640 forward is
# 200-400ms, so the loop is self-limiting to ~2-4 FPS single / ~0.5-1 FPS dual; this
# cap makes that honest and configurable instead of a free-running spin. 0 = uncapped.
DETECTION_FPS = float(os.environ.get("DETECTION_FPS", "8"))
# Per-candidate decode tracing. Off by default: the RAW/FILTER hooks emit one flushed
# line per candidate above a 0.02 floor (~40-100/frame/model) and grew the log to 55MB.
DETECT_LOG_ENABLED = _env_bool("DETECT_LOG_ENABLED")
# Verbosity floor for the whole detection pipeline trace. Accepts
# Structured trace verbosity: OFF/ERROR/WARN/INFO/DEBUG/TRACE; anything
# unrecognised falls back to INFO rather than raising, because a typo in an env
# var must not take the detector down. Independent of DETECT_LOG_ENABLED, which
# still controls the legacy per-frame file log: trace data is in-memory and
# cheap, that log is not.
DETECT_TRACE_LEVEL = str(os.environ.get("DETECT_TRACE_LEVEL", "OFF")).strip().upper() or "OFF"
# Bounded in-memory ring buffer of structured trace events served by
# /api/detection/trace. Bounded by construction so a long unattended run cannot
# grow memory; 0 disables the buffer while keeping stage timings in the status API.
# Clamped to 0..500 (ai/detection/detect_log.py TRACE_BUFFER_MAX) so an
# over-eager or mistyped value cannot turn the "bounded" buffer into a leak.
DETECT_TRACE_BUFFER = _env_int("DETECT_TRACE_BUFFER", 200, 0, 500)

# Unknown/generic object proposals (a companion to the known-class detector).
#   - UNKNOWN_DETECTION_ENABLED: run the model-free motion-foreground proposer
#     alongside the known detector (default on).
#   - UNKNOWN_MIN_AREA: smallest motion blob (fraction of frame) promoted.
#   - UNKNOWN_OVERLAP_IOU: a proposal overlapping a known detection above this
#     IoU is suppressed — the unknown feed never double-reports known classes.
#   - UNKNOWN_MOTION_THRESHOLD: pixel-threshold on the background difference.
UNKNOWN_DETECTION_ENABLED = not _env_bool("UNKNOWN_DETECTION_DISABLED")
UNKNOWN_MIN_AREA = float(os.environ.get("UNKNOWN_MIN_AREA", "0.004"))
UNKNOWN_OVERLAP_IOU = float(os.environ.get("UNKNOWN_OVERLAP_IOU", "0.35"))
UNKNOWN_MOTION_THRESHOLD = int(os.environ.get("UNKNOWN_MOTION_THRESHOLD", "25"))

# Held / unattended-object attendance monitoring (consumes the unknown feed).
# Thresholds are centralized here; the state machine itself lives in
# app.attendance.AttendanceMonitor.
ATTENDANCE_POLL_MS = int(os.environ.get("ATTENDANCE_POLL_MS", "150"))
#: Consecutive near-person frames before POSSIBLY_HELD becomes HELD.
ATTENDANCE_HELD_FRAMES = int(os.environ.get("ATTENDANCE_HELD_FRAMES", "3"))
#: RELEASED frames before an object is declared UNATTENDED (the alert trigger).
ATTENDANCE_UNATTENDED_FRAMES = int(os.environ.get("ATTENDANCE_UNATTENDED_FRAMES", "5"))
#: Frames a watched object may stay missing before the watch expires.
ATTENDANCE_TRACK_LOST_FRAMES = int(os.environ.get("ATTENDANCE_TRACK_LOST_FRAMES", "30"))
#: Arm-reach geometry: a hold candidate lives within this margin (× person
#: width) around the person AND below this fraction of person height (upper
#: torso/head band) — an object at the astronaut's feet is NOT "held".
ATTENDANCE_ARM_REACH = float(os.environ.get("ATTENDANCE_ARM_REACH", "0.6"))
ATTENDANCE_UPPER_BODY = float(os.environ.get("ATTENDANCE_UPPER_BODY", "0.45"))

# Unattended-object-in-container monitoring. The frame-count thresholds above drive
# the *unknown* hand-off chain; these drive the real reported failure, where a KNOWN
# object (a bottle, a tool) is placed in a container and the astronaut walks away.
#   - UNATTENDED_TIMEOUT_MS: wall-clock an object must be person-free before the
#     alert fires. Time-based, not frame-based, so it is independent of AI frame rate
#     (at 2-4 measured FPS, 5 frames would be 1.2-2.5s of wall clock and wildly variable).
#   - UNATTENDED_PROXIMITY: a person counts as attending when its box centre is within
#     this fraction of the frame diagonal of the object centre.
#   - UNATTENDED_CONTAINMENT: minimum fraction of the object box that must lie inside
#     a container box before the pair is reported as OBJECT_INSIDE_CONTAINER.
#   - UNATTENDED_CONTAINER_CLASSES / UNATTENDED_TRACKED_CLASSES: the vocabulary is
#     data here, never hardcoded logic; containers are what we look *into*, tracked
#     classes are what we look *at* (person is excluded by definition).
UNATTENDED_TIMEOUT_MS = int(os.environ.get("UNATTENDED_TIMEOUT_MS", "2000"))
UNATTENDED_PROXIMITY = float(os.environ.get("UNATTENDED_PROXIMITY", "0.18"))
UNATTENDED_CONTAINMENT = float(os.environ.get("UNATTENDED_CONTAINMENT", "0.60"))
UNATTENDED_CONTAINER_CLASSES = tuple(
    c.strip()
    for c in os.environ.get(
        "UNATTENDED_CONTAINER_CLASSES", "experiment_box,red_box,yellow_box,box,container,suitcase,briefcase"
    ).split(",")
    if c.strip()
)
UNATTENDED_TRACKED_CLASSES = tuple(
    c.strip()
    for c in os.environ.get(
        "UNATTENDED_TRACKED_CLASSES",
        "bottle,knife,pen,floating_tool,loose_cable,cup,mug,can,book,phone,laptop,tool,scissors",
    ).split(",")
    if c.strip()
)

# Activity perception stage (Phase 5C bridge / procedure-aware). Chooses which
# source feeds the state machine at runtime.
#   interaction -> event-grounded InteractionActivityPerception (DEFAULT for the
#           canonical experiment): runs the hand/object interaction tracker over
#           the camera feed and emits a step only when the tracker's events
#           satisfy that step's expectedEvents (a real PICK = MOVED episode, a
#           PLACE = settling in the target area). Visibility alone never fires.
#   live -> the camera-grounded LiveActivityPerception: emits a step only when
#           it actually sees the step's expectedObjects on camera.
#   mock -> deterministic MockActivityPerception (data-driven from the loaded
#           experiment, clearly labeled as mock — demos without vision).
#   sim  -> the original scripted SimulatedPerception (tests/backwards compat).
ACTIVITY_BACKEND = os.environ.get("ACTIVITY_BACKEND", "interaction").strip().lower()
# Live mode: accepted gap (ms) since the last camera inference before the scene
# is stale. Stopped camera / frozen feed / disabled detector -> experiment waits.
ACTIVITY_STALE_MS = int(os.environ.get("ACTIVITY_STALE_MS", "5000"))
# Base pacing (ms) between live perception polls.
ACTIVITY_POLL_MS = int(os.environ.get("ACTIVITY_POLL_MS", "700"))


def _target_area() -> tuple[float, float, float, float] | None:
    """The destination fixture as a normalized box, or ``None`` when unset.

    No shipped detector can see the target area: `experiment_custom.onnx` emits
    only red_box/yellow_box, yolov8n.onnx is COCO, and the heuristic detector is
    person/red/yellow. The destination is a *fixed* piece of station hardware,
    so its region is configuration, not perception - and pretending otherwise
    means `*_PLACED` can never fire and PLACE_* is unreachable on camera.

    Format: ``x1,y1,x2,y2`` normalized 0-1, left/top/right/bottom. Unset (the
    default) keeps the honest limitation: the interaction source will then
    report `targetAreaSource="none"` and refuse to ground PLACED.
    """
    raw = os.environ.get("ACTIVITY_TARGET_AREA", "").strip()
    if not raw:
        return None
    parts = [p for p in raw.replace(";", ",").split(",") if p.strip()]
    if len(parts) != 4:
        return None
    try:
        box = tuple(float(p) for p in parts)
    except ValueError:
        return None
    x1, y1, x2, y2 = box
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        return None
    return box  # type: ignore[return-value]


#: Normalized destination box for the interaction source, or None.
ACTIVITY_TARGET_AREA = _target_area()

# Optional absolute path to an experiment JSON. When unset, load_active_experiment
# prefers the canonical experiment/experiment.json, falling back to EXPERIMENTS_DIR.
EXPERIMENT_FILE = os.environ.get("EXPERIMENT_FILE", "").strip()

# Optional absolute path to the hazard knowledge base JSON. When unset, the
# canonical backend/app/safety/hazards.json is loaded.
HAZARDS_FILE = os.environ.get("HAZARDS_FILE", "").strip()

# --------------------------------------------------------------------------
# Astronaut safety & hazard monitoring (Phase 6+). This is the NEW core purpose
# of the application; the experiment pipeline is retained as a legacy demo
# fixture and does NOT drive the safety runtime.
# --------------------------------------------------------------------------

# Operational environment the hazard engine assumes. Do NOT claim the AI can
# infer this from an RGB camera — it is operational configuration.
#   microgravity | planetary
ENVIRONMENT_MODE = os.environ.get("ENVIRONMENT_MODE", "microgravity").strip().lower()

# Master switch for the safety monitor pipeline (default ON).
SAFETY_ENABLED = _env_bool("SAFETY_ENABLED") or os.environ.get("SAFETY_ENABLED", "").strip() == ""

# Monitoring loop pacing (ms between assessment cycles).
SAFETY_POLL_MS = int(os.environ.get("SAFETY_POLL_MS", "100"))

# Detection feed is considered stale (camera off / detector idle) after this gap.
SAFETY_STALE_MS = int(os.environ.get("SAFETY_STALE_MS", "5000"))

# How many consecutive frames a hazard must persist before it is CONFIRMED.
SAFETY_PERSIST_FRAMES = int(os.environ.get("SAFETY_PERSIST_FRAMES", "2"))

# How many frames a resolved hazard must stay gone before it is forgotten.
SAFETY_RESOLVE_FRAMES = int(os.environ.get("SAFETY_RESOLVE_FRAMES", "2"))

# Emergency source: which signals feed the astronaut injury/emergency candidates.
#   rules -> rule-based candidates derived from the object detection feed
#            (astronaut unobserved / prolonged immobility / collision risk)
#   sim   -> scripted emergency signals (demo/tests only, never production)
#   none  -> no emergency candidates are generated
EMERGENCY_BACKEND = os.environ.get("EMERGENCY_BACKEND", "rules").strip().lower()

# Rule-based emergency tuning (frames, snapshot windows).
EMERGENCY_ABSENT_FRAMES = int(os.environ.get("EMERGENCY_ABSENT_FRAMES", "8"))
EMERGENCY_STATIC_FRAMES = int(os.environ.get("EMERGENCY_STATIC_FRAMES", "30"))

# Alert deduplication / cooldown / escalation tuning.
ALERT_COOLDOWN_MS = int(os.environ.get("ALERT_COOLDOWN_MS", "15000"))
ALERT_ESCALATE_AFTER_MS = int(os.environ.get("ALERT_ESCALATE_AFTER_MS", "10000"))

# Earth escalation. When a confirmed incident reaches at least
# EARTH_ESCALATION_MIN_LEVEL, a local evidence package is generated. The
# package is NEVER claimed to have been transmitted — a real comms interface
# plugs in at the transport seam later.
EARTH_ESCALATION_ENABLED = _env_bool("EARTH_ESCALATION_ENABLED") or os.environ.get("EARTH_ESCALATION_ENABLED", "").strip() == ""
EARTH_ESCALATION_MIN_LEVEL = os.environ.get("EARTH_ESCALATION_MIN_LEVEL", "CRITICAL").strip().upper()

# Mock scenario for the deterministic demo detector (dev/testing only).
#   "" or "bas"  -> legacy BAS scene (person/red_box/yellow_box)
#   "space_station" -> static astronaut + floating tool + loose cable
#   "safety_sequence" -> astronaut then "astronaut leaves frame" emergency demo
MOCK_SCENE = os.environ.get("MOCK_SCENE", "").strip().lower()
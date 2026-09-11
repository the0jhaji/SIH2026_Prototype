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
#   heuristic -> model-free HSV color + motion detection, no weights needed
DETECTION_ENABLED = _env_bool("DETECTION_ENABLED")
DETECTION_BACKEND = os.environ.get("DETECTION_BACKEND", "mock").strip().lower()
DETECTION_MODEL_PATH = os.environ.get("DETECTION_MODEL_PATH", "detection/yolov8n.onnx")
DETECTION_CONF_THRESHOLD = float(os.environ.get("DETECTION_CONF_THRESHOLD", "0.5"))
DETECTION_POLL_MS = int(os.environ.get("DETECTION_POLL_MS", "100"))
# Explicit OpenCV thread pool size for the detector. 0 (default) leaves OpenCV's
# auto-detect untouched; a positive value caps oversubscription on small hosts.
DETECTION_CV_THREADS = int(os.environ.get("DETECTION_CV_THREADS", "0"))
# Temporal smoothing of the live detector output (raw -> stable feed):
#   - DETECTION_DEBOUNCE_FRAMES: consecutive frames a class/box must persist before
#     it is emitted as a stable detection (2-3 recommended; 1 disables debounce).
#   - DETECTION_EMA_ALPHA: EMA weight for confidence + box smoothing (0..1).
DETECTION_DEBOUNCE_FRAMES = int(os.environ.get("DETECTION_DEBOUNCE_FRAMES", "2"))
DETECTION_EMA_ALPHA = float(os.environ.get("DETECTION_EMA_ALPHA", "0.35"))

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

# Activity perception stage (Phase 5C bridge). Chooses which source feeds the
# state machine at runtime.
#   live -> the camera-grounded LiveActivityPerception (DEFAULT): emits a step
#           only when it actually sees the step's expectedObjects on camera.
#   mock -> deterministic MockActivityPerception (data-driven from the loaded
#           experiment, clearly labeled as mock — demos without vision).
#   sim  -> the original scripted SimulatedPerception (tests/backwards compat).
ACTIVITY_BACKEND = os.environ.get("ACTIVITY_BACKEND", "live").strip().lower()
# Live mode: accepted gap (ms) since the last camera inference before the scene
# is stale. Stopped camera / frozen feed / disabled detector -> experiment waits.
ACTIVITY_STALE_MS = int(os.environ.get("ACTIVITY_STALE_MS", "5000"))
# Base pacing (ms) between live perception polls.
ACTIVITY_POLL_MS = int(os.environ.get("ACTIVITY_POLL_MS", "700"))

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
SAFETY_POLL_MS = int(os.environ.get("SAFETY_POLL_MS", "500"))

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
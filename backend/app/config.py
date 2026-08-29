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
# machines without a webcam.
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "720"))
CAMERA_FPS = int(os.environ.get("CAMERA_FPS", "30"))
CAMERA_MOCK = _env_bool("CAMERA_MOCK")
CAMERA_JPEG_QUALITY = int(os.environ.get("CAMERA_JPEG_QUALITY", "70"))
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
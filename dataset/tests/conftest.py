"""Make `dataset_tool` (dataset dir) and the backend `camera` package importable
for the dataset tests (run from the repo root)."""

import sys
from pathlib import Path

DATASET = Path(__file__).resolve().parent.parent
BACKEND = DATASET.parent / "backend"
for path in (str(DATASET), str(BACKEND)):
    if path not in sys.path:
        sys.path.insert(0, path)
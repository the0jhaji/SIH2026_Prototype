"""Make the repo root importable so `ai.*` (backend style) and `detection.*` /
`pipeline.*` (ai-native style) both resolve under ai/.venv pytest."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
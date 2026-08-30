"""Loading and lookup helpers for configurable experiment definitions.

The canonical definition lives at ``experiment/experiment.json`` (analysed,
validated, and shared by every module that needs the activity vocabulary).
``backend/experiments/`` holds drop-in demo definitions; the first one in
sorted order is the fallback when no canonical file exists. An alternates path
can be forced with the ``EXPERIMENT_FILE`` env var.
"""

import json
from pathlib import Path
from typing import Optional

from .config import EXPERIMENT_FILE, EXPERIMENTS_DIR
from .schemas import ExperimentDef, StepDef

CANONICAL_EXPERIMENT = Path(__file__).resolve().parent.parent.parent / "experiment" / "experiment.json"


def load_experiment(path: Path) -> ExperimentDef:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ExperimentDef(**raw)


def load_active_experiment() -> ExperimentDef:
    candidates = []
    if EXPERIMENT_FILE:
        candidates.append(Path(EXPERIMENT_FILE))
    candidates.append(CANONICAL_EXPERIMENT)
    candidates.extend(sorted(EXPERIMENTS_DIR.glob("*.json")))
    for candidate in candidates:
        if candidate.is_file():
            return load_experiment(candidate)
    raise FileNotFoundError(
        f"No experiment definitions found (tried {EXPERIMENT_FILE!r}, {CANONICAL_EXPERIMENT}, {EXPERIMENTS_DIR})"
    )


def step_for_activity(experiment: ExperimentDef, activity: str) -> Optional[StepDef]:
    for step in experiment.steps:
        if step.activity == activity:
            return step
    return None


def expected_step(experiment: ExperimentDef, index: int) -> Optional[StepDef]:
    if 0 <= index < len(experiment.steps):
        return experiment.steps[index]
    return None
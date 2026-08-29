"""Loading and lookup helpers for configurable experiment definitions.

Definitions are JSON documents in backend/experiments/. The first definition
in the directory is treated as the active one; the directory is consumed in
sorted order so an operator can drop in a new sequence without code changes.
"""

import json
from pathlib import Path
from typing import Optional

from .config import EXPERIMENTS_DIR
from .schemas import ExperimentDef, StepDef


def load_experiment(path: Path) -> ExperimentDef:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ExperimentDef(**raw)


def load_active_experiment() -> ExperimentDef:
    candidates = sorted(EXPERIMENTS_DIR.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"No experiment definitions found in {EXPERIMENTS_DIR}")
    return load_experiment(candidates[0])


def step_for_activity(experiment: ExperimentDef, activity: str) -> Optional[StepDef]:
    for step in experiment.steps:
        if step.activity == activity:
            return step
    return None


def expected_step(experiment: ExperimentDef, index: int) -> Optional[StepDef]:
    if 0 <= index < len(experiment.steps):
        return experiment.steps[index]
    return None
"""Is the loaded model actually able to see the experiment vocabulary?

Pure and camera-free so both the detection service and the tests can call it
without a device. The vocabulary is DATA, read from the canonical
`dataset/experiment_detection/classes.json` — never a list written in Python,
because the two drifting apart is how a 2-class model ends up being described
in the UI as if it could see a container and two target areas.

The point of this module is that "detection is on" and "detection can see the
experiment objects" are different claims. A generic COCO detector is genuinely
running and genuinely finds `person`; it still cannot see a red box, and the
dashboard has to say so rather than showing an empty panel that looks like a
camera problem.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
EXPERIMENT_CLASSES_FILE = _ROOT / "dataset" / "experiment_detection" / "classes.json"
MODEL_CLASS_CONTRACT = "astra-experiment-detection/1"

NOT_READY_LABEL = "EXPERIMENT MODEL: NOT TRAINED / NOT READY"
READY_LABEL = "EXPERIMENT MODEL: READY"

_lock = threading.Lock()
_cached: Optional[list[str]] = None


def load_experiment_classes(refresh: bool = False) -> list[str]:
    """The six-class experiment vocabulary, in canonical index order.

    Falls back to an empty list when the contract file is unreadable: a missing
    contract must degrade the dashboard to "unknown vocabulary", never invent
    one. The caller turns that into the not-ready label.
    """
    global _cached
    with _lock:
        if _cached is not None and not refresh:
            return list(_cached)
        try:
            data = json.loads(EXPERIMENT_CLASSES_FILE.read_text(encoding="utf-8"))
            classes = [str(c) for c in data["classes"]]
        except Exception:  # noqa: BLE001 - diagnostics must never raise
            classes = []
        if classes:
            _cached = classes
        return list(classes)


def model_readiness(model_classes: Optional[Iterable[str]]) -> dict[str, Any]:
    """Can the loaded model emit every class the experiment procedure needs?

    `model_classes` is the loaded model's own `.names`/class list, i.e. what it
    can actually emit — not what the UI would like it to emit.
    """
    required = load_experiment_classes()
    available = set(model_classes or ())
    if not required:
        supported: list[str] = []
        missing: list[str] = []
        ready = False
    else:
        supported = [c for c in required if c in available]
        missing = [c for c in required if c not in available]
        ready = not missing
    return {
        "ready": ready,
        "label": READY_LABEL if ready else NOT_READY_LABEL,
        "required": required,
        "supported": supported,
        "missing": missing,
        "modelClassCount": len(available),
        # A model with fewer classes than the vocabulary is a *specialised*
        # detector, whatever it is named. Reported so the UI can say
        # "specialised" instead of implying a general model is running.
        "narrow": bool(available) and len(available) < len(required),
    }


def class_counts(detections: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Per-class counts for the diagnostics panel (raw or filtered)."""
    counts: dict[str, int] = {}
    for d in detections:
        name = str(d.get("class_name", "")) if isinstance(d, Mapping) else ""
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def partition_detections(
    detections: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Split detections into the experiment vocabulary and everything else.

    Membership is decided by the canonical class list, so a COCO `book` is
    always `generic`: presenting a generic model COCO output as an experiment
    object is the specific dishonesty this split exists to prevent.
    """
    experiment = set(load_experiment_classes())
    out: dict[str, list[dict[str, Any]]] = {
        "experiment": [],
        "generic": [],
        "unknown": [],
    }
    for d in detections:
        name = str(d.get("class_name", "")) if isinstance(d, Mapping) else ""
        if not name or name == "unknown_object":
            out["unknown"].append(dict(d))
        elif name in experiment:
            out["experiment"].append(dict(d))
        else:
            out["generic"].append(dict(d))
    return out

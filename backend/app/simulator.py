"""Simulated perception source.

Emits a scripted timeline of Detections that exercises every supported
outcome of the state machine: correct step, out-of-sequence step, skipped
step, repeated step, unknown activity and low-confidence detection.

This is a stand-in for the real perception pipeline (OpenCV -> YOLO -> Pose
-> Activity Recognition). It produces exactly the same Detection objects, so
the downstream state machine, WebSocket protocol and UI are unaffected by the
eventual swap.
"""

import asyncio
import time
from typing import AsyncIterator, List

from .schemas import Detection

DEFAULT_SIM_SCRIPT: List[dict] = [
    {"delay_ms": 1400, "activity": "PICK_MAIN_BOX", "confidence": 0.96},
    {"delay_ms": 2600, "activity": "OPEN_EXPERIMENT_BOX", "confidence": 0.91},
    {"delay_ms": 2000, "activity": "OPEN_EXPERIMENT_BOX", "confidence": 0.41},
    {"delay_ms": 2200, "activity": "PICK_YELLOW_BOX", "confidence": 0.88},
    {"delay_ms": 2200, "activity": "PICK_RED_BOX", "confidence": 0.93},
    {"delay_ms": 2200, "activity": "PLACE_RED_BOX", "confidence": 0.9},
    {"delay_ms": 2200, "activity": "PLACE_YELLOW_BOX", "confidence": 0.89},
    {"delay_ms": 2200, "activity": "PICK_RED_BOX", "confidence": 0.87},
    {"delay_ms": 2200, "activity": "WRITING_ON_SURFACE", "confidence": 0.72},
    {"delay_ms": 2200, "activity": "PICK_YELLOW_BOX", "confidence": 0.95},
    {"delay_ms": 2200, "activity": "PLACE_YELLOW_BOX", "confidence": 0.94},
]


class SimulatedPerception:
    """Produces Detections on a timeline. Drop-in for the real pipeline."""

    name = "simulated"

    def __init__(self, script: List[dict] | None = None) -> None:
        self.script = script or DEFAULT_SIM_SCRIPT

    async def detections(self) -> AsyncIterator[Detection]:
        for item in self.script:
            await asyncio.sleep(item["delay_ms"] / 1000.0)
            yield Detection(
                activity=item["activity"],
                confidence=item["confidence"],
                ts=int(time.time() * 1000),
            )
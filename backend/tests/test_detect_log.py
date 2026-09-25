"""[DETECT][...] observability logging — pure emitter + decode-level tracing.

Validates that the debug logger writes timestamped lines to its dedicated file,
that stage counters bump/reset, and that the YOLO decode hooks log RAW / FILTER
/ CLASS events WITHOUT changing the returned detections (behavior unchanged
proves the observability is truly non-invasive).

Exclusively camera-free, deterministic, in-memory inputs — no model weights.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import numpy as np
import pytest

# Same bootstrap as detection_service/detection_tracker: make the repo root
# importable so `ai` resolves from the backend venv.
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai.detection import detect_log
from ai.pipeline.yolo import postprocess_yolov8

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[\w+\] \[DETECT\]\[RAW\]")


@pytest.fixture()
def debug_log(tmp_path: Path) -> Path:
    """Redirect the singleton logger to a temp file for the duration of a test."""
    logger = detect_log._LOG
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    detect_log._setup_done = False
    detect_log.take_counters()
    target = detect_log.ensure_setup(root=str(tmp_path))
    assert isinstance(logger.handlers[0], logging.FileHandler)
    yield target
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    detect_log._setup_done = False


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_debug_lines_are_timestamped_into_dedicated_file(debug_log: Path) -> None:
    detect_log.dbg("RAW", "class=person conf=0.90 bbox=(1,2,3,4)")
    detect_log.dbg_info("FILTER", "reason=confidence class=red_box conf=0.10 threshold=0.25")

    lines = _lines(debug_log)
    raw = [l for l in lines if "[DETECT][RAW]" in l]
    filt = [l for l in lines if "[DETECT][FILTER]" in l]
    assert len(raw) == 1
    assert len(filt) == 1
    assert re.match(TIMESTAMP_RE, raw[0])
    assert "class=person conf=0.90" in raw[0]
    assert filt[0].startswith("20") and "[INFO]" in filt[0]


def test_counters_bump_and_take_resets(debug_log: Path) -> None:
    detect_log.bump("raw", 4)
    detect_log.bump("accepted", 2)
    detect_log.bump("rejected_confidence", 1)
    detect_log.bump("unknown", 1)

    snap = detect_log.take_counters()
    assert snap == {"raw": 4, "accepted": 2, "rejected_confidence": 1, "unknown": 1}
    assert detect_log.take_counters() == {"raw": 0, "accepted": 0, "rejected_confidence": 0, "unknown": 0}


def test_postprocess_logs_raw_filter_class_without_changing_output(debug_log: Path) -> None:
    # out shape (1, 4+3, N): [cx, cy, w, h, class0 score, class1, class2]
    out = np.zeros((1, 7, 3), dtype=np.float32)
    out[0, :, 0] = [0.5, 0.5, 0.6, 0.8, 0.9, 0.05, 0.02]  # person @ 0.90 -> accept
    out[0, :, 1] = [0.2, 0.2, 0.3, 0.3, 0.02, 0.10, 0.05]  # red_box @ 0.10 -> reject
    out[0, :, 2] = [0.9, 0.1, 0.2, 0.2, 0.0, 0.0, 0.80]  # score on class 2, outside 2-class range

    result = postprocess_yolov8(
        out,
        input_size=640,
        scale=1.0,
        dx=0.0,
        dy=0.0,
        frame_width=640,
        frame_height=480,
        classes=["person", "red_box"],
        conf_threshold=0.25,
        iou_threshold=0.45,
    )

    names = [d.class_name for d in result]
    assert names == ["person"]  # behavior unchanged: only the high-confidence in-range box survives

    lines = _lines(debug_log)
    raw = [l for l in lines if "[DETECT][RAW]" in l]
    filt = [l for l in lines if "[DETECT][FILTER]" in l]
    cls = [l for l in lines if "[DETECT][CLASS]" in l]
    cls_map = [l for l in lines if "[DETECT][CLASS_MAP]" in l]

    assert any("class=person conf=0.90" in l for l in raw)
    assert any("class=red_box conf=0.10" in l for l in raw)
    assert any("reason=confidence class=red_box conf=0.10 threshold=0.25" in l for l in filt)
    assert any("ACCEPT class=person" in l for l in filt)
    assert any("class_name=unknown conf=0.80" in l for l in cls)
    assert any("source=2 mapped_to=None" in l for l in cls_map)

    counters = detect_log.take_counters()
    assert counters["raw"] == 2
    assert counters["accepted"] == 1
    assert counters["rejected_confidence"] == 1
    assert counters["unknown"] == 1
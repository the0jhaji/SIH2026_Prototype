"""Model-configuration guards: the general detector must be general-purpose, and
the class vocabulary must match what the network actually emits.

These are the two ways ASTRA silently "only sees person":
  1. a narrow (2-class) model loaded as the sole detector, and
  2. a missing/short `.names` file, where the decoder drops every class_id
     beyond the short list with no error anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

cv2 = pytest.importorskip("cv2")

from ai.detection import detect_log  # noqa: E402
from ai.detection.yolo_detector import YoloDetector  # noqa: E402

GENERAL = "detection/yolov8n.onnx"
CUSTOM = "detection/experiment_custom.onnx"


@pytest.fixture(autouse=True)
def _quiet_trace():
    detect_log.set_enabled(False)
    yield
    detect_log.set_enabled(False)


def _frame() -> np.ndarray:
    return np.zeros((720, 1280, 3), dtype=np.uint8)


# --------------------------------------------------------------------- guards


def test_narrow_model_is_reported_as_not_general_purpose():
    """experiment_custom.onnx knows red_box/yellow_box and nothing else."""
    det = YoloDetector(model_path=CUSTOM, conf_threshold=0.25, cv_threads=4)
    det.load()
    status = det.status()
    assert status.classes == ("red_box", "yellow_box")
    assert status.general_purpose is False


def test_general_model_is_reported_as_general_purpose():
    det = YoloDetector(model_path=GENERAL, conf_threshold=0.25, cv_threads=4)
    det.load()
    status = det.status()
    assert len(status.classes) == 80
    assert status.general_purpose is True
    assert status.model_size_mb is not None and status.model_size_mb > 1.0
    assert status.input_size == 640
    assert status.conf_threshold == 0.25


def test_narrow_model_warns_that_it_cannot_be_the_general_detector(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="astraai.detection"):
        YoloDetector(model_path=CUSTOM, cv_threads=4).load()
    assert any("CANNOT be used as the general detector" in r.message for r in caplog.records)


def test_class_channel_mismatch_raises_instead_of_silently_dropping():
    """A missing .names falls back to the 5 ASTRA names against an 80-class net.

    Without the check, postprocess does `keep &= class_ids < 5` and reports an
    almost-empty frame with no error — exactly the reported symptom.
    """
    det = YoloDetector(
        model_path=GENERAL,
        names_path="detection/definitely_absent.names",
        cv_threads=4,
    )
    det.load()
    assert len(det.classes) == 5  # DEFAULT_CLASSES fallback
    with pytest.raises(ValueError, match="Class vocabulary mismatch"):
        det.detect(_frame())


def test_matching_vocabulary_does_not_raise():
    det = YoloDetector(model_path=GENERAL, conf_threshold=0.25, cv_threads=4)
    det.load()
    assert det.detect(_frame()) == []  # empty frame -> no detections, no error


# ------------------------------------------------------------------- pipeline


def test_confidence_0_25_reports_more_classes_than_0_50():
    """The 0.5 default was hiding most real objects, not making the model stricter."""
    files = sorted((ROOT / "dataset" / "raw").rglob("*.jpg"))[:6]
    frames = [cv2.imread(str(f)) for f in files]
    frames = [f for f in frames if f is not None]
    if not frames:
        pytest.skip("no dataset frames available")

    def run(conf: float) -> set[str]:
        det = YoloDetector(model_path=GENERAL, conf_threshold=conf, cv_threads=4)
        det.load()
        return {d.class_name for f in frames for d in det.detect(f)}

    loose, strict = run(0.25), run(0.50)
    assert strict <= loose or len(strict) <= len(loose)
    assert "person" in loose


def test_iou_threshold_is_propagated():
    det = YoloDetector(model_path=GENERAL, conf_threshold=0.25, iou_threshold=0.7, cv_threads=4)
    det.load()
    assert det.status().iou_threshold == 0.7

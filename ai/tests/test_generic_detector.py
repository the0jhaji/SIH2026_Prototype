"""Tests for the generic (unknown-object) proposal detector.

Model-free motion foreground: honest for synthetic input, imperfect for real
scenes — that honesty (returning nothing for static objects, never inventing a
known class id) is exactly what these tests pin down.
"""

import cv2
import numpy as np

from detection.generic import GenericProposalDetector

# The 8 trained YOLO classes — the generic detector must never emit these.
KNOWN_CLASSES = {
    "person",
    "knife",
    "pen",
    "red_box",
    "yellow_box",
    "floating_tool",
    "loose_cable",
    "bottle",
}


def make_frame(x: int, y: int, w: int = 40, h: int = 40, color: tuple = (255, 255, 255)) -> np.ndarray:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, -1)
    return frame


def test_static_object_never_emits_unknown() -> None:
    # Moving object: first frame seeds the background; a moved object emits.
    det = GenericProposalDetector()
    det.detect(make_frame(200, 100))
    moved = det.detect(make_frame(240, 100))
    assert any(d.class_name == "unknown_object" for d in moved)

    # The SAME object held still afterwards adapts into the background -> gone.
    static = GenericProposalDetector(bg_alpha=0.9)
    static.detect(make_frame(200, 100))
    for _ in range(4):
        assert static.detect(make_frame(200, 100)) == []


def test_moving_object_produces_unknown_detection() -> None:
    det = GenericProposalDetector()
    det.detect(make_frame(200, 100))
    out = det.detect(make_frame(240, 100))
    assert len(out) == 1
    d = out[0]
    assert d.class_name == "unknown_object"
    assert d.confidence >= det.BASE_CONF  # honesty floor: never inflated
    assert d.confidence <= det.MAX_CONF
    # The box covers the moved region (morphology may expand it slightly).
    assert d.x2 > d.x1 and d.y2 > d.y1


def test_multi_object_proposals() -> None:
    det = GenericProposalDetector()
    det.detect(make_frame(100, 80))
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (120, 80), (200, 160), (255, 255, 255), -1)
    cv2.rectangle(frame, (400, 300), (500, 380), (120, 120, 120), -1)
    out = det.detect(frame)
    assert len(out) == 2
    assert all(d.class_name == "unknown_object" for d in out)


def test_blank_and_initial_frames_return_nothing() -> None:
    det = GenericProposalDetector()
    assert det.detect(np.zeros((0, 0, 3), dtype=np.uint8)) == []
    # First real frame seeds the background — no output yet.
    det2 = GenericProposalDetector()
    assert det2.detect(np.zeros((480, 640, 3), dtype=np.uint8)) == []


def test_generic_status_reports_mode_and_class() -> None:
    st = GenericProposalDetector().status()
    assert st.detector_type == "generic"
    assert st.model_loaded is True
    assert st.classes == ("unknown_object",)


def test_conf_threshold_filters_low_area_blobs() -> None:
    """Small blobs yield lower confidence; a high threshold drops them."""
    det = GenericProposalDetector(conf_threshold=0.99)
    det.detect(make_frame(200, 100))
    assert det.detect(make_frame(220, 100)) == []


def test_tiny_motion_below_min_area_is_suppressed() -> None:
    """A motion region smaller than the configured floor never fires."""
    # min_area is a fraction of the frame; 0.3 of a 480x640 frame is ~92k px,
    # far above the small 40x40 test square — so no motion may be reported.
    det = GenericProposalDetector(min_area=0.3)
    det.detect(make_frame(200, 100))
    assert det.detect(make_frame(260, 100)) == []
    # The same motion IS reported when the floor is small enough.
    det2 = GenericProposalDetector(min_area=0.0005)
    det2.detect(make_frame(200, 100))
    assert det2.detect(make_frame(260, 100)) != []


def test_generic_detector_never_uses_known_class_ids() -> None:
    """Proposals carry exactly ``unknown_object`` — never a trained class name."""
    det = GenericProposalDetector()
    det.detect(make_frame(200, 100))
    out = det.detect(make_frame(240, 100))
    assert out
    for d in out:
        assert d.class_name == "unknown_object"
        assert d.class_name not in KNOWN_CLASSES
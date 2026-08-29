import numpy as np

from pipeline.annotate import draw_detections
from pipeline.detections import Box, ObjectDetection
from pipeline.mock import MockDetector

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def test_draw_returns_copy_not_input() -> None:
    dets = MockDetector().detect(FRAME)
    out = draw_detections(FRAME, dets)
    assert out is not FRAME  # input must be kept raw for the backend
    assert out.shape == FRAME.shape
    assert out.dtype == FRAME.dtype


def test_draw_composes_pixels() -> None:
    out = draw_detections(FRAME, MockDetector().detect(FRAME))
    # Boxes + labels add coloured pixels somewhere on the canvas.
    assert out.max() > 0


def test_draw_empty_list_returns_blank_copy() -> None:
    out = draw_detections(FRAME, [])
    assert out.shape == FRAME.shape
    assert (out == FRAME).all()


def test_draw_unknown_class_uses_palette() -> None:
    det = ObjectDetection(
        class_name="mystery_object",
        confidence=0.5,
        bounding_box=Box(x=10, y=10, width=50, height=50),
        timestamp=1,
    )
    out = draw_detections(FRAME, [det])
    assert out.max() > 0
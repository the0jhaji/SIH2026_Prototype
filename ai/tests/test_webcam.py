import numpy as np
import pytest

from pipeline.webcam import NullSource, WebcamSource


def test_null_source_context_and_read() -> None:
    with NullSource(320, 240, max_frames=2) as src:
        assert src.open()
        ok1, f1 = src.read()
        ok2, f2 = src.read()
        ok3, f3 = src.read()
        assert ok1 and f1 is not None and f1.shape == (240, 320, 3)
        assert ok2 and f2 is not None
        assert not ok3 and f3 is None
        assert f1.dtype == np.uint8


def test_null_source_props() -> None:
    src = NullSource(1280, 720)
    assert src.width == 1280
    assert src.height == 720


def test_webcam_source_construction_and_release() -> None:
    # Constructing must never touch hardware; open() is exercised only when a
    # camera is present (skipped here — CI boxes have none).
    src = WebcamSource(index=0, width=640, height=480)
    assert src.index == 0
    assert src.width == 640
    assert src.height == 480
    src.release()  # idempotent no-op when never opened
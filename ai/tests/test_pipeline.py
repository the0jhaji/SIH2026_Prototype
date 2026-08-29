import threading

from pipeline.mock import MockDetector
from pipeline.pipeline import CameraPipeline
from pipeline.webcam import NullSource


def test_pipeline_emits_frames() -> None:
    source = NullSource(320, 240, max_frames=5)
    pipeline = CameraPipeline(source, MockDetector())
    seen = []

    def on_frame(df) -> None:
        seen.append(df)

    pipeline.run(on_frame, max_frames=5)
    assert len(seen) == 5
    for i, df in enumerate(seen):
        assert df.frame_index == i
        assert df.frame is not None
        assert df.annotated is not None
        assert df.annotated.shape == df.frame.shape
        assert len(df.detections) == 5
        assert df.timestamp > 0


def test_pipeline_no_annotate() -> None:
    source = NullSource(320, 240)
    pipeline = CameraPipeline(source, MockDetector(), annotate=False)
    seen = []
    pipeline.run(lambda df: seen.append(df), max_frames=3)
    assert len(seen) == 3
    assert all(df.annotated is None for df in seen)


def test_pipeline_stop_event_halts_early() -> None:
    source = NullSource(320, 240)
    pipeline = CameraPipeline(source, MockDetector())
    stop = threading.Event()
    seen = []

    def on_frame(df) -> None:
        seen.append(df)
        if len(seen) >= 3:
            stop.set()

    pipeline.run(on_frame, stop_event=stop)
    assert len(seen) == 3


def test_pipeline_stops_at_source_end() -> None:
    source = NullSource(320, 240, max_frames=4)
    pipeline = CameraPipeline(source, MockDetector())
    seen = []
    pipeline.run(lambda df: seen.append(df))
    assert len(seen) == 4


def test_pipeline_clamps_mock_boxes_to_small_frame() -> None:
    source = NullSource(160, 120)
    pipeline = CameraPipeline(source, MockDetector())
    seen = []
    pipeline.run(lambda df: seen.append(df), max_frames=1)
    assert len(seen) == 1
    for det in seen[0].detections:
        box = det.bounding_box
        assert box.x + box.width <= 160
        assert box.y + box.height <= 120
import numpy as np
import pytest

from pipeline.yolo import DEFAULT_CLASSES, letterbox, postprocess_yolov8, resolve_weights_path


# ------------------------------------------------------------------ letterbox

def test_letterbox_wide_frame() -> None:
    canvas, scale, dx, dy = letterbox(np.zeros((1080, 1920, 3), dtype=np.uint8), size=640)
    assert canvas.shape == (640, 640, 3)
    assert canvas[0, 0].tolist() == [114, 114, 114]  # padded area
    assert abs(scale - 640 / 1920) < 1e-6
    assert dx == 0.0
    assert dy == 140.0
    # The image (nh=360) sits vertically centered.
    assert not np.all(canvas[140] == 114)


def test_letterbox_tall_frame_pads_horizontal() -> None:
    canvas, scale, dx, dy = letterbox(np.zeros((1920, 1080, 3), dtype=np.uint8), size=640)
    assert canvas.shape == (640, 640, 3)
    assert abs(scale - 640 / 1920) < 1e-6
    assert dy == 0.0
    assert abs(dx - (640 - 360) / 2) < 1e-6


def test_letterbox_small_upscale_default() -> None:
    canvas, scale, _, _ = letterbox(np.zeros((160, 240, 3), dtype=np.uint8), size=640)
    assert canvas.shape == (640, 640, 3)
    assert scale == 640 / 240


# ----------------------------------------------------- yolov8 output decoding

def _tensor(normalized: np.ndarray) -> np.ndarray:
    """Build a (1, 4+C, N) onnx-style output with a single score column."""
    tensor = np.zeros((1, 4 + len(DEFAULT_CLASSES), 1), dtype=np.float32)
    for feat, value in enumerate(normalized):
        tensor[0, feat, 0] = value
    return tensor


def test_decode_known_detection() -> None:
    # 640x480 frame → letterbox: scale 1.0, dy = (640-480)/2 = 80.
    # A box at normalized (0.5, 0.5), 0.15x0.3 → canvas px 272,144 → 368,336
    # then unpad by 80 on y.
    out = _tensor([0.5, 0.5, 0.15, 0.30, 0.0, 0.0, 1.0, 0.0, 0.0])
    dets = postprocess_yolov8(
        out,
        input_size=640,
        scale=1.0,
        dx=0.0,
        dy=80.0,
        frame_width=640,
        frame_height=480,
        classes=DEFAULT_CLASSES,
    )
    assert len(dets) == 1
    det = dets[0]
    assert det.class_name == "red_box"
    assert det.confidence == pytest.approx(1.0)
    assert det.bounding_box.as_tuple() == (272, 144, 96, 192)


def test_decode_accepts_transposed_tensor() -> None:
    out = _tensor([0.5, 0.5, 0.15, 0.30, 0.0, 0.0, 1.0, 0.0, 0.0])
    transposed = np.transpose(out, (0, 2, 1))  # (1, N, 4+C)
    assert transposed.shape == (1, 1, 9)
    dets = postprocess_yolov8(transposed, input_size=640, scale=1.0, dx=0.0, dy=80.0,
                              frame_width=640, frame_height=480, classes=DEFAULT_CLASSES)
    assert len(dets) == 1
    assert dets[0].class_name == "red_box"


def test_decode_filters_low_confidence() -> None:
    out = _tensor([0.5, 0.5, 0.15, 0.30, 1.0, 0.0, 0.0, 0.0, 0.0])  # person at 1.0
    low = out.copy()
    low[0, 4, 0] = 0.05
    assert postprocess_yolov8(low, input_size=640, scale=1.0, dx=0.0, dy=80.0,
                              frame_width=640, frame_height=480, classes=DEFAULT_CLASSES) == []
    assert len(postprocess_yolov8(out, input_size=640, scale=1.0, dx=0.0, dy=80.0,
                                  frame_width=640, frame_height=480,
                                  classes=DEFAULT_CLASSES)) == 1


def test_decode_ignores_classes_outside_map() -> None:
    # Model trained with 21 classes; configured map only knows 5. The known
    # detector (person idx 0) must survive, the out-of-range one (idx 20) must
    # be dropped. N=2 keeps the feature/detection axes unambiguous.
    out = np.zeros((1, 4 + 21, 2), dtype=np.float32)
    out[0, :4, 0] = [0.5, 0.5, 0.15, 0.30]
    out[0, 4 + 0, 0] = 0.9  # person
    out[0, :4, 1] = [0.5, 0.5, 0.15, 0.30]
    out[0, 4 + 20, 1] = 0.9  # index beyond the class list → dropped
    dets = postprocess_yolov8(out, input_size=640, scale=1.0, dx=0.0, dy=80.0,
                              frame_width=640, frame_height=480, classes=DEFAULT_CLASSES)
    assert [d.class_name for d in dets] == ["person"]


def test_nms_deduplicates_overlapping_boxes() -> None:
    out = np.zeros((1, 4 + len(DEFAULT_CLASSES), 2), dtype=np.float32)
    out[0, :4, 0] = [0.40, 0.40, 0.20, 0.20]
    out[0, 4 + 0, 0] = 0.9  # person, high
    out[0, :4, 1] = [0.41, 0.41, 0.20, 0.20]
    out[0, 4 + 0, 1] = 0.6  # person, lower → suppressed
    dets = postprocess_yolov8(out, input_size=640, scale=1.0, dx=0.0, dy=80.0,
                              frame_width=640, frame_height=480, classes=DEFAULT_CLASSES)
    assert len(dets) == 1
    assert dets[0].confidence == pytest.approx(0.9)


def test_nms_keeps_distinct_classes() -> None:
    out = np.zeros((1, 4 + len(DEFAULT_CLASSES), 2), dtype=np.float32)
    out[0, :4, 0] = [0.40, 0.40, 0.20, 0.20]
    out[0, 4 + 0, 0] = 0.9  # person
    out[0, :4, 1] = [0.40, 0.40, 0.20, 0.20]
    out[0, 4 + 4, 1] = 0.8  # target_area
    dets = postprocess_yolov8(out, input_size=640, scale=1.0, dx=0.0, dy=80.0,
                              frame_width=640, frame_height=480, classes=DEFAULT_CLASSES)
    assert sorted(d.class_name for d in dets) == ["person", "target_area"]


# ------------------------------------------------ mismatched class-width tensors

def test_decode_wider_model_behind_small_names() -> None:
    # A COCO model (4 + 80 features) decoded through a 5-name override: the
    # feature axis no longer matches 4 + len(classes), so orientation must be
    # inferred from the shape, not the class count. person (class id 0) must
    # survive; an out-of-range class id (56) must be dropped.
    out = np.zeros((1, 84, 2), dtype=np.float32)
    out[0, :4, 0] = [0.5, 0.5, 0.15, 0.30]
    out[0, 4 + 0, 0] = 0.9  # person
    out[0, :4, 1] = [0.5, 0.5, 0.15, 0.30]
    out[0, 4 + 56, 1] = 0.9  # chair-like id 56 → outside the 5-name map
    dets = postprocess_yolov8(out, input_size=640, scale=1.0, dx=0.0, dy=80.0,
                              frame_width=640, frame_height=480, classes=DEFAULT_CLASSES)
    assert [d.class_name for d in dets] == ["person"]


def test_decode_pixel_space_boxes_normalized() -> None:
    # Some exports emit cx,cy,w,h already in input_size pixels instead of
    # normalized [0, 1]; the decoder must normalize them before decoding.
    # 0.5*640 / 0.15*640 / 0.3*640 in pixels == the reference score below.
    out = np.zeros((1, 4 + len(DEFAULT_CLASSES), 1), dtype=np.float32)
    out[0, :4, 0] = [0.5 * 640, 0.5 * 640, 0.15 * 640, 0.30 * 640]
    out[0, 4 + 2, 0] = 1.0  # red_box
    dets = postprocess_yolov8(out, input_size=640, scale=1.0, dx=0.0, dy=80.0,
                              frame_width=640, frame_height=480, classes=DEFAULT_CLASSES)
    assert len(dets) == 1
    assert dets[0].bounding_box.as_tuple() == (272, 144, 96, 192)


def test_decode_pixel_boxes_wide_model_transposed() -> None:
    # Combined regression: wider model (84 features) + pixel-space boxes.
    out = np.zeros((1, 84, 2), dtype=np.float32)
    out[0, :4, 0] = [0.5 * 640, 0.5 * 640, 0.15 * 640, 0.30 * 640]
    out[0, 4 + 0, 0] = 0.9  # person
    dets = postprocess_yolov8(out, input_size=640, scale=1.0, dx=0.0, dy=80.0,
                              frame_width=640, frame_height=480, classes=DEFAULT_CLASSES)
    assert [d.class_name for d in dets] == ["person"]
    assert dets[0].bounding_box.as_tuple() == (272, 144, 96, 192)


# ---------------------------------------------------------------- model paths

def test_resolve_default_weights_tail() -> None:
    path = resolve_weights_path("yolov8n.onnx")
    assert path.name == "yolov8n.onnx"
    assert "models" in path.parts


def test_resolve_absolute_is_passthrough(tmp_path) -> None:
    custom = tmp_path / "custom.onnx"
    custom.write_bytes(b"x")
    assert resolve_weights_path(str(custom)) == custom


def test_weights_missing_raises_helpful_error(tmp_path, monkeypatch) -> None:
    from pipeline.yolo import YoloDetector

    monkeypatch.setenv("BAS_MODELS_DIR", str(tmp_path))
    detector = YoloDetector(model_path="nope.onnx")
    with pytest.raises(FileNotFoundError, match="models/yolo"):
        detector.load()
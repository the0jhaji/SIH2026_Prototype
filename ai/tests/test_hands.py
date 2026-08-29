"""Hand-landmark sources: mock tracker is deterministic and hardware-free;
the MediaPipe wrapper is lazy (no dependency at import time)."""

import numpy as np

from pipeline.hand import (
    FINGER_TIPS,
    HAND_JOINTS,
    MediaPipeHandTracker,
    MockHandTracker,
    pixel_distance,
    resolve_pose_model_path,
)
from pipeline.detections import Box


def test_mock_hand_tracker_shape() -> None:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    hands = MockHandTracker().track(frame)
    assert len(hands) == 1
    hand = hands[0]
    assert len(hand.landmarks) == HAND_JOINTS
    assert all(0.0 <= lm.x <= 1.0 and 0.0 <= lm.y <= 1.0 for lm in hand.landmarks)
    assert hand.box is not None


def test_mock_hand_deterministic() -> None:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    points = lambda: [  # noqa: E731
        (lm.x, lm.y) for lm in MockHandTracker(phase=1.0).track(frame)[0].landmarks
    ]
    assert points() == points()


def test_fingertips_are_the_near_test_points() -> None:
    frame_size = (640, 480)
    hand = MockHandTracker().track(np.zeros((480, 640, 3), dtype=np.uint8))[0]
    # distance uses fingertip pixels — must be finite and non-negative
    box = Box(300, 200, 80, 60)
    d = pixel_distance(hand, box, frame_size)
    assert 0 <= d < float("inf")


def test_media_pipe_import_is_lazy() -> None:
    # Constructing must not import mediapipe (keeps tests/CI free of it).
    tracker = MediaPipeHandTracker(model_path="whatever.task")
    assert tracker._landmarker is None
    assert tracker.requires_weights is True


def test_pose_model_resolution_tail() -> None:
    path = resolve_pose_model_path("hand_landmarker.task")
    assert path.name == "hand_landmarker.task"
    assert "pose" in path.parts


def test_finger_tips_constant() -> None:
    assert FINGER_TIPS == (4, 8, 12, 16, 20)
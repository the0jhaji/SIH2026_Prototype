"""Stateful InteractionTracker behaviour: NEAR transitions, temporal MOVED,
and PLACED only after authenticated movement — never proximity alone."""

import pytest

from pipeline.detections import Box, ObjectDetection
from pipeline.hand import HandLandmarkSet
from pipeline.interaction.demo import make_hand
from pipeline.interaction.tracker import InteractionConfig, InteractionTracker

FRAME = (640, 480)
# red_box diag = 100 px
RED = Box(100, 100, 80, 60)
TARGET = Box(300, 300, 200, 150)  # centre (400, 375)
RED_DIAG = 100.0


def _det(class_name: str, box: Box) -> ObjectDetection:
    return ObjectDetection(class_name=class_name, confidence=0.9, bounding_box=box, timestamp=1)


def _red(box: Box) -> ObjectDetection:
    return _det("red_box", box)


def _target() -> ObjectDetection:
    return _det("target_area", TARGET)


def _hand_near(box: Box) -> HandLandmarkSet:
    return make_hand(box.cx / FRAME[0], box.cy / FRAME[1])


def _hand_far() -> HandLandmarkSet:
    return make_hand(0.03, 0.03)


def names(events) -> list[str]:
    return [e.name for e in events]


def test_empty_updates_produce_nothing() -> None:
    tracker = InteractionTracker()
    for _ in range(5):
        assert tracker.update([], [], FRAME, 1) == []


def test_static_object_never_moves_or_places() -> None:
    tracker = InteractionTracker()
    out = []
    for i in range(10):
        out += tracker.update([_red(RED), _target()], [_hand_far()], FRAME, i)
    assert "RED_MOVED" not in names(out)
    assert "RED_PLACED" not in names(out)


def test_slow_motion_below_threshold_is_not_moved() -> None:
    tracker = InteractionTracker()
    out = []
    box = Box(RED.x, RED.y, 80, 60)
    for i in range(8):  # 15 px per frame < 30 px threshold
        box = Box(box.x + 15, box.y, 80, 60)
        out += tracker.update([_red(box), _target()], [_hand_far()], FRAME, i)
    assert "RED_MOVED" not in names(out)


def test_single_fast_frame_is_not_moved() -> None:
    tracker = InteractionTracker()
    out = []
    out += tracker.update([_red(RED), _target()], [_hand_far()], FRAME, 0)
    out += tracker.update([_red(Box(260, 260, 80, 60)), _target()], [_hand_far()], FRAME, 1)
    out += tracker.update([_red(Box(260, 260, 80, 60)), _target()], [_hand_far()], FRAME, 2)
    # one moving frame (68 px), then static → moving_frames never reaches 2
    assert "RED_MOVED" not in names(out)


def test_sustained_motion_fires_moved_once() -> None:
    tracker = InteractionTracker()
    out = []
    box = RED
    for i in range(8):
        box = Box(box.x + 60, box.y + 60, 80, 60)  # ~85 px per frame
        out += tracker.update([_red(box), _target()], [_hand_far()], FRAME, i)
    moved = [e for e in out if e.name == "RED_MOVED"]
    assert len(moved) == 1
    assert moved[0].hand_id is None
    assert moved[0].displacement is not None and moved[0].displacement > 30
    assert "RED_PLACED" not in names(out)  # never settled yet


def test_moved_reports_hand_when_near() -> None:
    tracker = InteractionTracker()
    out = []
    box = RED
    for i in range(4):
        box = Box(box.x + 60, box.y + 60, 80, 60)
        out += tracker.update([_red(box), _target()], [_hand_near(box)], FRAME, i)
    moved = [e for e in out if e.name == "RED_MOVED"]
    assert len(moved) == 1
    assert moved[0].hand_id is not None  # held-through-motion is witnessed


def test_place_requires_prior_move_into_target() -> None:
    tracker = InteractionTracker()
    out = []
    # 1–2: static near hand; 3–4: move briskly into target; 5–8: settle inside target.
    steps = [
        RED,
        RED,
        Box(220, 220, 80, 60),
        Box(340, 360, 80, 60),
        Box(400, 375, 80, 60),
        Box(400, 375, 80, 60),
        Box(400, 375, 80, 60),
        Box(400, 375, 80, 60),
    ]
    for i, box in enumerate(steps):
        out += tracker.update([_red(box), _target()], [_hand_near(box)], FRAME, i)
    seq = names(out)
    assert "RED_MOVED" in seq
    assert "RED_PLACED" in seq
    assert seq.index("RED_MOVED") < seq.index("RED_PLACED")
    placed = [e for e in out if e.name == "RED_PLACED"]
    assert len(placed) == 1
    assert placed[0].in_target_area is True


def test_sitting_in_target_from_start_never_places() -> None:
    tracker = InteractionTracker()
    out = []
    rest = Box(400, 375, 80, 60)  # centre already inside target
    for i in range(12):
        out += tracker.update([_red(rest), _target()], [_hand_near(rest)], FRAME, i)
    assert "RED_PLACED" not in names(out)
    assert "RED_MOVED" not in names(out)


def test_move_then_settle_outside_target_never_places() -> None:
    tracker = InteractionTracker()
    out = []
    steps = [
        RED,
        RED,
        Box(200, 200, 80, 60),
        Box(300, 300, 80, 60),
        Box(380, 420, 80, 60),
        Box(400, 480, 80, 60),  # centre (440, 510) outside target
        Box(400, 480, 80, 60),
        Box(400, 480, 80, 60),
        Box(400, 480, 80, 60),
    ]
    for i, box in enumerate(steps):
        out += tracker.update([_red(box), _target()], [_hand_near(box)], FRAME, i)
    assert "RED_MOVED" in names(out)
    assert "RED_PLACED" not in names(out)


def test_no_target_area_means_no_place_even_at_rest() -> None:
    tracker = InteractionTracker()
    out = []
    steps = [
        RED,
        RED,
        Box(200, 200, 80, 60),
        Box(300, 300, 80, 60),
        Box(300, 300, 80, 60),
        Box(300, 300, 80, 60),
        Box(300, 300, 80, 60),
    ]
    for i, box in enumerate(steps):
        out += tracker.update([_red(box)], [_hand_near(box)], FRAME, i)  # no target_area
    assert "RED_MOVED" in names(out)
    assert "RED_PLACED" not in names(out)


def test_near_event_on_entry_only_and_again_on_reentry() -> None:
    c = InteractionConfig(near_mult=0.9)
    tracker = InteractionTracker(c)
    out = []
    near = [_red(RED), _target()]
    far = [_red(RED), _target()]
    for _ in range(3):
        out += tracker.update(near, [_hand_near(RED)], FRAME, 1)
    for _ in range(3):
        out += tracker.update(far, [_hand_far()], FRAME, 2)
    for _ in range(3):
        out += tracker.update(near, [_hand_near(RED)], FRAME, 3)
    near_events = [e for e in out if e.name == "HAND_NEAR_RED"]
    assert len(near_events) == 2  # enter + re-enter only (no spam while holding)
    assert all(e.hand_id is not None for e in near_events)


def test_near_only_for_the_object_being_touched() -> None:
    tracker = InteractionTracker()
    out = []
    yellow = Box(320, 100, 80, 60)
    for _ in range(3):
        out += tracker.update(
            [_red(RED), _det("yellow_box", yellow), _target()],
            [_hand_near(yellow)],
            FRAME,
            1,
        )
    seq = set(names(out))
    assert "HAND_NEAR_YELLOW" in seq
    assert "HAND_NEAR_RED" not in seq


def test_two_same_class_instances_track_independently() -> None:
    tracker = InteractionTracker()
    out = []
    a = RED
    b = Box(420, 100, 80, 60)
    for i in range(4):
        a = Box(a.x + 60, a.y + 60, 80, 60)
        b = Box(b.x + 60, b.y + 60, 80, 60)
        scenes = [_red(a), _red(b), _target()]
        out += tracker.update(scenes, [_hand_far()], FRAME, i)
    moved = [e for e in out if e.name == "RED_MOVED"]
    assert len(moved) == 2  # one per instance


def test_gap_between_detections_does_not_count_as_motion() -> None:
    tracker = InteractionTracker()
    out = []
    box = RED
    # three frames of motion (first frame only seeds the position) → MOVED
    for i in range(3):
        box = Box(box.x + 60, box.y + 60, 80, 60)
        out += tracker.update([_red(box), _target()], [_hand_far()], FRAME, i)
    assert len([e for e in out if e.name == "RED_MOVED"]) == 1
    for _ in range(2):
        out += tracker.update([_target()], [_hand_far()], FRAME, 99)
    # object reappears at a wildly different spot; the jump must NOT be
    # credited as motion (tracking gap), so no second MOVED fires.
    out += tracker.update([_red(Box(20, 20, 80, 60)), _target()], [_hand_far()], FRAME, 100)
    out += tracker.update([_red(Box(20, 20, 80, 60)), _target()], [_hand_far()], FRAME, 101)
    moved = [e for e in out if e.name == "RED_MOVED"]
    assert len(moved) == 1


def test_deterministic_given_same_input() -> None:
    steps = [RED, RED, Box(220, 220, 80, 60), Box(340, 360, 80, 60), Box(400, 375, 80, 60)]
    runs = []
    for _ in range(2):
        tracker = InteractionTracker()
        out = []
        for i, box in enumerate(steps):
            out += tracker.update([_red(box), _target()], [_hand_near(box)], FRAME, i)
        runs.append([(e.name, e.confidence, e.hand_id) for e in out])
    assert runs[0] == runs[1]


def test_yellow_events_parallel_red() -> None:
    tracker = InteractionTracker()
    out = []
    steps = [
        Box(400, 100, 80, 60),
        Box(440, 120, 80, 60),
        Box(470, 200, 80, 60),
        Box(400, 375, 80, 60),
        Box(400, 375, 80, 60),
        Box(400, 375, 80, 60),
        Box(400, 375, 80, 60),
    ]
    for i, box in enumerate(steps):
        out += tracker.update(
            [_red(RED), _det("yellow_box", box), _target()],
            [_hand_near(box)],
            FRAME,
            i,
        )
    seq = names(out)
    assert "YELLOW_MOVED" in seq
    assert "YELLOW_PLACED" in seq
    assert "HAND_NEAR_YELLOW" in seq
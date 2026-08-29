"""Full-chain test over the coherent MockScene: both hands' interaction
sequences must unfold in the honest order — near → moved → placed."""

from pipeline.interaction.demo import MockScene
from pipeline.interaction.tracker import InteractionTracker

FRAME = (1280, 720)


def test_scene_drives_full_event_chain() -> None:
    scene = MockScene()
    tracker = InteractionTracker()
    events = []
    for _ in range(140):
        detections, hands = scene.step(FRAME)
        events += tracker.update(detections, hands, FRAME, scene._tick * 33)

    names = [e.name for e in events]
    # All six requested interaction events appear.
    required = {
        "HAND_NEAR_RED",
        "HAND_NEAR_YELLOW",
        "RED_MOVED",
        "YELLOW_MOVED",
        "RED_PLACED",
        "YELLOW_PLACED",
    }
    assert required.issubset(set(names))

    # Per-object causality: NEAR before MOVED before PLACED (first occurrences).
    first: dict[str, int] = {}
    for i, name in enumerate(names):
        first.setdefault(name, i)
    assert first["HAND_NEAR_YELLOW"] < first["YELLOW_MOVED"] < first["YELLOW_PLACED"]
    assert first["HAND_NEAR_RED"] < first["RED_MOVED"] < first["RED_PLACED"]

    # Yellow episode completes before the red episode begins.
    assert first["YELLOW_PLACED"] < first["HAND_NEAR_RED"]

    # MOVED events during the demo were hand-witnessed (held).
    moved = [e for e in events if e.name in {"RED_MOVED", "YELLOW_MOVED"}]
    assert moved and all(e.hand_id is not None for e in moved)
    assert moved and all(e.confidence > 0.7 for e in moved)

    placed = [e for e in events if e.name in {"RED_PLACED", "YELLOW_PLACED"}]
    assert placed and all(e.in_target_area is True for e in placed)


def test_scene_is_deterministic() -> None:
    def run() -> list[str]:
        scene = MockScene()
        tracker = InteractionTracker()
        out = []
        for _ in range(140):
            detections, hands = scene.step(FRAME)
            out += [e.name for e in tracker.update(detections, hands, FRAME, scene._tick)]
        return out

    assert run() == run()
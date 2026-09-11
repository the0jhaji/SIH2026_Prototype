"""TemporalTracker (raw -> stable debounce + EMA) unit tests.

Camera-free and detector-free by design: it consumes Detection objects only.
"""

from app.detection_tracker import TemporalTracker
from ai.detection.types import Detection


def det(class_name="chair", conf=0.80, x1=100, y1=100, x2=200, y2=200, ts=1):
    return Detection(class_name=class_name, confidence=conf, x1=x1, y1=y1, x2=x2, y2=y2, timestamp=ts)


def test_single_frame_is_pending_not_stable() -> None:
    t = TemporalTracker(debounce_frames=2)
    assert t.update([det()]) == []
    assert t.pending == 1


def test_debounce_frames_is_push_and_never_invents() -> None:
    t = TemporalTracker(debounce_frames=2)
    assert t.update([det()]) == []
    stable = t.update([det()])
    assert [d.class_name for d in stable] == ["chair"]
    # No object ever appears that the raw feed did not actually report.
    assert t.update([]) == []
    assert t.pending == 0


def test_ema_smooths_confidence() -> None:
    t = TemporalTracker(debounce_frames=2, alpha_conf=0.35)
    t.update([det(conf=0.80)])
    t.update([det(conf=0.70)])
    t.update([det(conf=0.60)])
    out = t.update([det(conf=0.60, ts=4)])
    assert len(out) == 1
    # ema chain with a=0.35: 0.80 -> 0.765 -> 0.70725 -> 0.66971
    assert abs(out[0].confidence - 0.6697) < 1e-3


def test_box_is_ema_smoothed() -> None:
    t = TemporalTracker(debounce_frames=2, alpha_box=0.5)
    t.update([det(x1=100, x2=200)])
    out = t.update([det(x1=110, x2=204, ts=2)])
    assert out[0].x1 == 105 and out[0].x2 == 202


def test_disappearance_is_immediate_but_grace_keeps_track() -> None:
    t = TemporalTracker(debounce_frames=2)
    t.update([det()])
    t.update([det()])
    assert len(t.update([])) == 0           # gone this frame -> not emitted
    # One-frame flicker: returns without re-running the full debounce.
    out = t.update([det(ts=3)])
    assert [d.class_name for d in out] == ["chair"]


def test_distinct_classes_are_separate_tracks() -> None:
    t = TemporalTracker(debounce_frames=2)
    t.update([det("chair"), det("person")])
    t.update([det("chair", ts=2), det("person", ts=2)])
    out = t.update([det("chair", ts=3), det("person", ts=3)])
    assert sorted(d.class_name for d in out) == ["chair", "person"]


def test_slightly_moving_box_stays_one_track() -> None:
    t = TemporalTracker(debounce_frames=2)
    t.update([det(x1=100, y1=100, x2=200, y2=200)])
    t.update([det(x1=104, y1=100, x2=206, y2=202)])  # IoU > 0.3 overlap
    out = t.update([det(x1=104, y1=100, x2=206, y2=202, ts=3)])
    assert [d.class_name for d in out] == ["chair"]


def test_true_positive_survives_jitter_no_label_flip() -> None:
    """"pen -> bottle -> pen" confusion must not reach stable output."""
    t = TemporalTracker(debounce_frames=3)
    t.update([det("pen", conf=0.6)])
    t.update([det("pen", conf=0.6)])
    t.update([det("pen", conf=0.6)])
    stab = [d.class_name for d in t.update([det("pen", conf=0.6, ts=4)])]
    assert stab == ["pen"]

    t2 = TemporalTracker(debounce_frames=3)
    assert t2.update([det("pen", conf=0.6)]) == []
    assert t2.update([det("bottle", conf=0.6)]) == []
    assert t2.update([det("pen", conf=0.6)]) == []
    assert t2.update([det("bottle", conf=0.6)]) == []


def test_debounce_one_passes_through() -> None:
    t = TemporalTracker(debounce_frames=1)
    out = t.update([det()])
    assert [d.class_name for d in out] == ["chair"]